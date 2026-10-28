"""Bounded offline event/feedback regressions; the DOM double does not prove layout."""
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import portal_checks
import portable_site
import review_feedback
import review_page


HOSTILE = "x');globalThis.injected=true;//\"><img src=x onerror=alert(1)>"
TOPIC = 'topic-' + HOSTILE
FILE = 'models/' + HOSTILE + '.sql'
ASSETS = review_page.ASSETS


def fixture():
    data = {'schema_version': 1, 'page_mode': 'status', 'selected_categories': [], 'files': [], 'file_count': 0,
            'projection': {'selected_artifact_count': 0, 'excluded_artifact_count': 0},
            'engagement': {'engagement_id': 'security-review', 'context_sha256': 'a' * 64},
            'review': {'title': 'Synthetic security review', 'models': [
                {'id': HOSTILE, 'name': HOSTILE, 'layer': 'gold', 'columns': [], 'domain': 'test'},
                {'id': '__proto__', 'name': 'Prototype-shaped ID', 'layer': 'gold', 'columns': []}],
                'relationships': [], 'topic_join_trees': {'topics': [{'id': TOPIC}]}}}
    presentation = review_page.page_model(data, {})
    presentation['topics'] = [{'topic': TOPIC, 'label': TOPIC, 'base': HOSTILE, 'area': presentation['areas'][0]['id'],
        'path': FILE, 'joins': [], 'views': [HOSTILE], 'fields': [], 'dashboards': [], 'view_files': {}, 'desc': '', 'group': '', 'ai': ''},
        {'topic': 'inferred-only', 'label': 'Not canonical', 'base': HOSTILE, 'area': 'missing', 'path': FILE,
         'joins': [], 'views': [], 'fields': [], 'dashboards': [], 'view_files': {}, 'desc': '', 'group': '', 'ai': ''}]
    presentation['files'] = [{'id': 'code', 'path': FILE, 'category': 'implementation', 'page': 'review/code/safe.html'}]
    presentation['models'][0]['artifact_id'] = 'code'
    return data, presentation


def envelope(page, version=2, topic=None):
    parsed, data = portal_checks.parse_page(page)
    raw = {s['attrs'].get('id'): s['source'] for s in parsed.scripts}
    response = {'schema_version': version, 'kind': 'model_review_feedback', 'request_only': True,
                'engagement_id': data['engagement']['engagement_id'],
                'context_sha256': data['engagement']['context_sha256'],
                'page_data_sha256': hashlib.sha256(raw['delivery-data'].encode()).hexdigest(),
                'comments': [{'model_id': None if topic else HOSTILE, 'type': 'question', 'text': 'Confirm this scope.'}]}
    if version == 2:
        response['review_page_data_sha256'] = hashlib.sha256(raw['review-page-data'].encode()).hexdigest() if 'review-page-data' in raw else None
        response['comments'][0]['topic_id'] = topic
    return response


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attributes = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


@unittest.skipUnless(shutil.which('node'), 'Node required for explicit offline JavaScript checks')
class ReviewPageSecurityTests(unittest.TestCase):
    def run_js(self, data, presentation, assertions):
        scripts = (ASSETS / 'review.js').read_text()
        prelude = r'''
const assert=require('node:assert/strict');
Object.defineProperty(globalThis,'crypto',{value:require('node:crypto').webcrypto,configurable:true});
const elements=new Map(),listeners={};
class E{constructor(){this.value='';this.textContent='';this.innerHTML='';this.dataset={};this.style={};this.hidden=false;this.classList={add(){},remove(){},toggle(){}};}hasAttribute(){return true;}setAttribute(){}querySelectorAll(){return [];}scrollIntoView(){}focus(){this.focused=true;}select(){this.selected=true;}append(){}click(){globalThis.downloadName=this.download;}remove(){}}
const get=id=>{if(!elements.has(id))elements.set(id,new E());return elements.get(id)};
const document={getElementById:get,querySelectorAll:()=>[],querySelector:()=>new E(),createElement:()=>new E(),body:new E(),addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
get('delivery-data').textContent=RAW_DATA;get('review-page-data').textContent=RAW_PAGE;
const location={hash:'#overview'},window={scrollTo(){}};
function addEventListener(){}function setTimeout(fn){fn()}
Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText:async()=>{throw Error('blocked')}}},configurable:true});
URL.createObjectURL=()=>{throw Error('blocked')};URL.revokeObjectURL=()=>{};
'''
        source = 'const RAW_DATA=' + json.dumps(review_page._encode(data)) + ';const RAW_PAGE=' + json.dumps(review_page._encode(presentation)) + ';\n' + prelude + scripts + '\n(async()=>{\n' + assertions + '\n})().catch(error=>{console.error(error);process.exitCode=1});'
        result = subprocess.run([shutil.which('node'), '-'], input=source, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_hostile_names_are_data_in_all_click_surfaces(self):
        data, presentation = fixture()
        for inline in (True, False):
            with self.subTest(inline=inline):
                presentation['inline_files'] = inline
                result = self.run_js(data, presentation, r'''
rModel();insp(P.models[0].id);const inspector=get('insp').innerHTML;inspTopic(P.topics[0].topic);rDelivery();
const fragments=[link(P.models[0].id),link('__proto__'),fileLink(P.files[0].path),get('architecture').innerHTML,get('lineage').innerHTML,inspector,get('insp').innerHTML,get('flist').innerHTML];
listeners.click[0]({target:{closest:()=>({dataset:{action:'inspect-model',value:P.models[0].id}})},preventDefault(){}});
listeners.keydown[0]({key:'Enter',target:{closest:()=>({dataset:{action:'inspect-topic',value:P.topics[0].topic}})},preventDefault(){}});
assert.equal(globalThis.injected,undefined);assert(Object.hasOwn(M,'__proto__'));
let prevented=false;listeners.click[0]({target:{closest:()=>({dataset:{action:'filter-dictionary'}})},preventDefault(){prevented=true}});assert.equal(prevented,false);
assert.equal(localHref('javascript:alert(1)'),null);assert.equal(localHref(' javascript:alert(1)'),null);assert.equal(localHref('//evil.test'),null);assert.equal(localHref('review/code/file name.html'),'review/code/file name.html');
console.log(JSON.stringify({fragments}));
''')
                parsed = Markup()
                for fragment in result['fragments']:
                    parsed.feed(fragment)
                self.assertNotIn('img', parsed.tags)
                self.assertFalse(any(k.lower().startswith('on') for k, _ in parsed.attributes))
                self.assertIn(('data-value', HOSTILE), parsed.attributes)
                self.assertIn(('data-value', TOPIC), parsed.attributes)

    def test_browser_feedback_roundtrip_and_copy_download_fallback(self):
        data, presentation = fixture()
        for inline in (True, False):
            presentation['inline_files'] = inline
            page = review_page.render(data, presentation)
            result = self.run_js(data, presentation, r'''
rFeedback();assert(!feedbackTopics.has('inferred-only'));
get('fb-table').value=String(feedbackSubjects.findIndex(s=>s.topic_id===P.topics[0].topic));get('fb-kind').value='question';get('fb-text').value='Confirm this topic.';
await dispatchAction({dataset:{action:'feedback-copy'}});assert.equal(get('fb-fallback').hidden,false);assert.equal(get('fb-json').selected,true);assert.match(get('fb-note').textContent,/Clipboard unavailable/);
const response=JSON.parse(get('fb-json').value);assert.equal(response.comments[0].topic_id,P.topics[0].topic);
await dispatchAction({dataset:{action:'feedback-download'}});assert.match(get('fb-note').textContent,/Download unavailable/);
URL.createObjectURL=()=> 'blob:synthetic';await dispatchAction({dataset:{action:'feedback-download'}});assert.equal(globalThis.downloadName,'model-review-feedback.json');
get('fb-table').value='999';await exportFeedback('copy');assert.equal(get('fb-fallback').hidden,true);assert.equal(get('fb-json').value,'');
console.log(JSON.stringify(response));
''')
            self.assertEqual(review_feedback.verify_feedback(page, result)['status'], 'current_feedback_request')

    def test_v1_compatibility_and_v2_rejects_stale_or_unknown_subjects(self):
        data, presentation = fixture()
        page = review_page.render(data, presentation)
        self.assertEqual(review_feedback.verify_feedback(page, envelope(page, 1))['status'], 'current_feedback_request')
        response = envelope(page, topic=TOPIC)
        self.assertEqual(review_feedback.verify_feedback(page, response)['status'], 'current_feedback_request')
        mutations = [dict(response, page_data_sha256='0' * 64), dict(response, context_sha256='0' * 64),
                     dict(response, review_page_data_sha256='0' * 64), dict(response, request_only=False),
                     dict(response, approved=True)]
        for subject in ({'topic_id': 'inferred-only'}, {'topic_id': TOPIC, 'model_id': HOSTILE}, {'type': 'approve'}):
            changed = copy.deepcopy(response)
            changed['comments'][0].update(subject)
            mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(ValueError):
                review_feedback.verify_feedback(page, changed)
        altered = copy.deepcopy(presentation)
        altered['title'] = 'Changed presentation'
        with self.assertRaisesRegex(ValueError, 'presentation'):
            review_feedback.verify_feedback(review_page.render(data, altered), response)

    def test_partitioned_feedback_uses_canonical_ids_and_scripts_have_no_handlers(self):
        data, _ = fixture()
        compact = {'kind': 'partitioned_review', 'engagement': data['engagement'], 'models': data['review']['models'],
                   'model_count': 2, 'files': [], 'file_count': 0, 'topic_diagrams': [{'id': TOPIC}]}
        sections = ('model', 'code', 'migration', 'validation')
        body = '<nav>' + ''.join(f'<a data-nav="{s}" href="#{s}">{s}</a>' for s in sections) + '</nav>'
        body += ''.join(f'<section id="{s}" class="review-section" data-section></section>' for s in sections)
        page = portable_site._page('Synthetic large review', body, compact, index=True)
        for response in (envelope(page, 1), envelope(page, topic=TOPIC)):
            self.assertEqual(review_feedback.verify_feedback(page, response)['status'], 'current_feedback_request')
        response = envelope(page, topic='absent')
        with self.assertRaisesRegex(ValueError, 'topic outside'):
            review_feedback.verify_feedback(page, response)
        script = (ASSETS / 'review.js').read_text()
        self.assertNotRegex(script, r'\bon(?:click|input|change|keydown)\s*=')
        checked = subprocess.run([shutil.which('node'), '--check', str(ASSETS / 'review.js')], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("script-src-attr 'none'", (ASSETS / 'review.html').read_text())


if __name__ == '__main__':
    unittest.main()
