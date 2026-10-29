"""Mandatory Chromium checks, intentionally outside default ``tests`` discovery.

Install .github/requirements/browser.txt and its matching Chromium, then run this
file directly. Missing dependencies, a missing browser and skipped tests fail.
"""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_domain_review_page import files, page_module, review, semantic_context


class DomainReviewBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel='chromium')
        except BaseException:
            cls.playwright.stop()
            raise
        print('Chromium runtime:', cls.browser.version, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dma-domain-browser-')
        self.addCleanup(self.temp.cleanup)
        self.context = self.browser.new_context(offline=True, service_workers='block')
        self.addCleanup(self.context.close)
        self.tab = self.context.new_page()
        self.errors, self.network = [], []
        self.tab.on('pageerror', lambda error: self.errors.append(str(error)))
        self.tab.on('request', lambda request: self.network.append(request.url)
                    if request.url.startswith(('http:', 'https:')) else None)

    def open_page(self, data=None, embedded_overrides=None):
        data = data or page_module.project(review(), files(), model_context=semantic_context())
        content = page_module.render(data)
        if embedded_overrides:
            # Bypass Python validation deliberately: client escaping must still
            # protect a tampered data block without changing the authorized JS.
            embedded = page_module.page_data(content)
            embedded['dashboards'][0].update(embedded_overrides)
            content = re.sub(r'(?<=id="domain-review-data">).*?(?=</script>)',
                             lambda _: page_module._encode(embedded), content, flags=re.S)
        target = Path(self.temp.name) / 'START_HERE.html'
        target.write_text(content, encoding='utf-8')
        self.tab.goto(target.as_uri())
        expect(self.tab.locator('#v-overview')).to_be_visible()

    def assert_offline_and_clean(self):
        self.assertEqual(self.network, [], 'The offline review attempted a network request')
        self.assertEqual(self.errors, [])

    def test_all_tabs_model_topic_and_code_inspectors_work_offline(self):
        self.open_page()
        for view in page_module.VIEWS:
            self.tab.locator(f'#nav button[data-v="{view}"]').click()
            expect(self.tab.locator(f'#v-{view}')).to_be_visible()
        self.tab.locator('#nav button[data-v="model"]').click()
        self.tab.locator('#abody [data-act="model"]').first.click()
        expect(self.tab.locator('#insp')).to_be_visible()
        expect(self.tab.locator('#insp')).to_contain_text('Grain:')
        self.tab.keyboard.press('Escape')
        expect(self.tab.locator('#insp')).not_to_be_visible()
        self.tab.locator('#spills [data-v="topics"]').click()
        self.tab.locator('#abody [data-act="topic"]').first.click()
        expect(self.tab.locator('#insp')).to_be_visible()
        expect(self.tab.locator('#insp')).to_contain_text('Base view:')
        unbound = self.tab.locator('#insp tr').filter(has_text='unbound_lookup').last
        expect(unbound).to_contain_text('Unverified warehouse binding')
        self.assertEqual(unbound.locator('[data-act="model"]').count(), 0)
        self.tab.locator('#insp [data-act="file"]').first.click()
        expect(self.tab.locator('#v-code')).to_be_visible()
        expect(self.tab.locator('#fview')).to_contain_text('base_view:')
        self.assert_offline_and_clean()

    def test_hostile_text_and_tampered_tile_values_stay_inert(self):
        payload = '<svg data-dma-probe onload="globalThis.__dmaProbe=1"></svg>'
        data = page_module.project(review(), files(), model_context=semantic_context())
        data['meta']['title'] = payload
        for model in data['models']:
            model['desc'] = payload
        data['topics'][0]['label'] = payload
        for row in data['files']:
            row['content'] = '</script>' + payload
        self.open_page(data, {'n_query_tiles': 1, 'n_served': payload,
                              'n_partly_served': payload, 'n_not_served': payload})
        expect(self.tab.locator('#v-overview h1')).to_contain_text(payload)
        expect(self.tab.locator('#v-overview')).to_contain_text(payload + ' served')
        self.tab.locator('#nav button[data-v="model"]').click()
        self.tab.locator('#abody [data-act="model"]').first.click()
        expect(self.tab.locator('#insp')).to_contain_text(payload)
        self.tab.locator('#insp [data-act="file"]').first.click()
        expect(self.tab.locator('#fview')).to_contain_text('</script>' + payload)
        self.tab.locator('#nav button[data-v="model"]').click()
        self.tab.locator('#spills [data-v="topics"]').click()
        self.tab.locator('#abody [data-act="topic"]').first.click()
        expect(self.tab.locator('#insp h2')).to_have_text(payload)
        self.assertEqual(self.tab.locator('[data-dma-probe]').count(), 0)
        self.assertTrue(self.tab.evaluate('globalThis.__dmaProbe === undefined'))
        self.assert_offline_and_clean()

    def test_csp_blocks_injected_inline_handlers_and_scripts(self):
        self.tab.add_init_script("""globalThis.__dmaViolations = [];
            document.addEventListener('securitypolicyviolation', event =>
                globalThis.__dmaViolations.push(event.effectiveDirective));""")
        self.open_page()
        self.tab.evaluate("""() => {
            const button = document.createElement('button');
            button.id = 'inline-handler-probe';
            button.textContent = 'CSP probe';
            button.setAttribute('onclick', 'globalThis.__dmaHandlerRan = true');
            document.body.appendChild(button);
            const script = document.createElement('script');
            script.textContent = 'globalThis.__dmaScriptRan = true';
            document.body.appendChild(script);
        }""")
        self.tab.locator('#inline-handler-probe').click()
        self.tab.wait_for_function("globalThis.__dmaViolations.includes('script-src-attr') && "
                                   "globalThis.__dmaViolations.includes('script-src-elem')")
        self.assertTrue(self.tab.evaluate('globalThis.__dmaHandlerRan === undefined && '
                                         'globalThis.__dmaScriptRan === undefined'))
        self.assert_offline_and_clean()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DomainReviewBrowserTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and result.testsRun == 3 and not result.skipped else 1)
