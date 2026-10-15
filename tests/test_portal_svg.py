"""SVG reconstruction checks with parsed-node stubs, not browser/CSP/visual QA."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/assets/guided-delivery/portal-svg.js'
SVG = 'http://www.w3.org/2000/svg'


def parsed_tree(source):
    """Prepare DOM-shaped fixtures; the Node stub deliberately has no XML parser."""
    def name(value):
        if value.startswith('{'):
            namespace, local = value[1:].split('}', 1)
            return namespace, local
        return None, value

    def element(node):
        namespace, local = name(node.tag)
        result = {'tag': local, 'namespace': namespace, 'attributes': [], 'children': []}
        for key, value in node.attrib.items():
            attr_ns, attr_local = name(key)
            result['attributes'].append({'name': attr_local, 'namespaceURI': attr_ns, 'value': value})
        if node.text:
            result['children'].append(node.text)
        for child in node:
            result['children'].append(element(child))
            if child.tail:
                result['children'].append(child.tail)
        return result
    try:
        return element(ET.fromstring(source))
    except ET.ParseError:
        return {'tag': 'parsererror', 'namespace': 'http://www.mozilla.org/newlayout/xml/parsererror.xml', 'attributes': [], 'children': ['Malformed XML']}


HARNESS = r"""
const assert = require('node:assert/strict');
class TestNode {
  constructor(tag, namespace, text) { this.nodeType=tag?1:3;this.localName=tag;this.namespaceURI=namespace;this.nodeValue=text;this.childNodes=[];this.parentNode=null;this._attributes=[]; }
  get attributes(){return this._attributes;}
  setAttribute(name,value){const existing=this._attributes.find(item=>item.name===name);if(existing)existing.value=String(value);else this._attributes.push({name,value:String(value),namespaceURI:null});}
  getAttribute(name){return this._attributes.find(item=>item.name===name)?.value??null;}
  hasAttribute(name){return this._attributes.some(item=>item.name===name);}
  appendChild(child){child.parentNode=this;this.childNodes.push(child);return child;}
  get textContent(){return this.nodeType===3?this.nodeValue:this.childNodes.map(child=>child.textContent).join('');}
  set textContent(value){this.childNodes=[];if(value)this.appendChild(new TestNode(null,null,value));}
}
function unpack(value){if(typeof value==='string')return new TestNode(null,null,value);const node=new TestNode(value.tag,value.namespace);node._attributes=value.attributes.map(item=>({...item}));value.children.forEach(child=>node.appendChild(unpack(child)));return node;}
function pack(node){if(node.nodeType===3)return node.nodeValue;return {tag:node.localName,namespace:node.namespaceURI,attributes:node.attributes.map(item=>({...item})),children:node.childNodes.map(pack)};}
function nodes(root,tag){return [root,...root.childNodes.flatMap(child=>child.nodeType===1?nodes(child):[])].filter(node=>!tag||node.localName===tag);}
const escaped=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function serialize(node){return node.nodeType===3?escaped(node.nodeValue):'<'+node.localName+node.attributes.map(item=>' '+item.name+'="'+escaped(item.value)+'"').join('')+'>'+node.childNodes.map(serialize).join('')+'</'+node.localName+'>';}
const fixtures=new Map(FIXTURES.map(([source,tree])=>[source,tree]));
globalThis.document={createElementNS:(namespace,tag)=>new TestNode(tag,namespace),createTextNode:text=>new TestNode(null,null,text)};
globalThis.DOMParser=class {parseFromString(source,mime){assert.equal(mime,'image/svg+xml');assert(fixtures.has(source),'Unregistered parsed fixture');const root=unpack(fixtures.get(source));return {documentElement:root,getElementsByTagName:tag=>nodes(root,tag)};}};
function roundTrip(root,namespace){const serialized=serialize(root);fixtures.set(serialized,pack(root));return PortalSvg.sanitize(serialized,namespace);}
"""


@unittest.skipUnless(shutil.which('node'), 'Node is needed for SVG sanitizer checks')
class PortalSvgTests(unittest.TestCase):
    def run_js(self, sources, assertions):
        fixtures = [(source, parsed_tree(source)) for source in sources]
        harness = HARNESS.replace('FIXTURES', json.dumps(fixtures))
        script = harness + '\n' + SCRIPT.read_text() + '\nconst sources=' + json.dumps(sources) + ';\n' + assertions
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standalone_script_parses(self):
        result = subprocess.run([shutil.which('node'), '--check', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_styles_colors_markers_and_metadata_survive_without_active_content(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg" id="source" viewBox="0 0 100 100">
<style>svg#source { font-family: 'IBM Plex Sans', sans-serif; } .node rect {fill:rgb(21, 90, 120);stroke:#abc} .edge {marker-end:url(#arrow)}</style>
<defs><marker id="arrow" orient="auto"><path d="M 0 0 L 4 4" fill="#123456"/></marker></defs>
<g class="node" data-model-id="schema.orders" data-model-name="A complete exceptionally long table name — 订单" data-unapproved="remove"><rect width="50" height="50"/><text>Order &amp; line</text></g>
<path class="edge" d="M 0 0 L 50 50" stroke="hsl(12, 20%, 40%)" fill="none"/></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'main'),css=nodes(clean,'style')[0].textContent;
assert(css.includes('#portal-svg-main-root .node rect{fill:rgb(21, 90, 120);stroke:#abc}'));
assert(css.includes("font-family:'IBM Plex Sans', sans-serif"));
const marker=nodes(clean,'marker')[0];assert(css.includes('url(#'+marker.getAttribute('id')+')'));
const group=nodes(clean,'g')[0];assert.equal(group.getAttribute('data-model-name'),'A complete exceptionally long table name — 订单');
assert.equal(group.getAttribute('data-model-id'),'schema.orders');assert.equal(group.hasAttribute('data-unapproved'),false);
assert.equal(nodes(clean,'text')[0].textContent,'Order & line');assert.equal(nodes(clean,'rect')[0].hasAttribute('fill'),false);
assert.deepEqual(pack(roundTrip(clean,'main')),pack(clean));
""")

    def test_removes_active_elements_namespaces_links_events_and_external_resources(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:h="http://www.w3.org/1999/xhtml" onload="run()" xml:base="https://bad.example/">
<script>run()</script><foreignObject><h:div>foreign</h:div></foreignObject><iframe/><object/><image href="https://bad.example/pixel"/><use xlink:href="#safe"/><a href="javascript:run()"><text>link</text></a><animate attributeName="href"/><h:rect/>
<rect id="safe" ONCLICK="run()" href="javascript:run()" xlink:href="https://bad.example/" src="data:text/html,bad" fill="url(https://bad.example/fill)" stroke="url(data:image/svg+xml,bad)" style="fill:url(//bad.example/x);stroke:#abc;filter:url(#safe);position:fixed" constructor="bad"/>
<style>@import url('https://bad.example/css'); @media screen {.bad{fill:red}} .good{fill:teal;background:url(https://bad.example/)} body{color:red} .bad:hover{fill:red}</style></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'safe'),output=serialize(clean);
assert.deepEqual(nodes(clean).map(node=>node.localName),['svg','rect','style']);
assert(!/bad\.example|javascript:|data:|onload|ONCLICK|href|src=|xml:base|constructor=|filter:|position:|@import|@media|body\{|:hover/.test(output));
const rect=nodes(clean,'rect')[0];assert.equal(rect.getAttribute('fill'),'#ffffff');assert.equal(rect.getAttribute('style'),'stroke:#abc');
assert.equal(nodes(clean,'style')[0].textContent,'#portal-svg-safe-root .good{fill:teal}');
assert.deepEqual(pack(roundTrip(clean,'safe')),pack(clean));
""")

    def test_css_escapes_comments_unknown_rules_and_properties_are_conservative(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg"><style>.bad{fill:u\\72l(https://bad.example/)}</style><rect style="fill:u\\72l(https://bad.example/);stroke:red"/><style>.good{fill:/*safe*/#fff;stroke:u/**/rl(https://bad.example/);font-weight:700!important} @supports (x:y){.x{fill:red}} .good > text{fill:navy}</style></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'css'),styles=nodes(clean,'style');
assert.equal(styles[0].textContent,'');assert.equal(nodes(clean,'rect')[0].getAttribute('style'),null);
assert.equal(styles[1].textContent,'#portal-svg-css-root .good{fill:#fff;font-weight:700!important}\n#portal-svg-css-root .good > text{fill:navy}');
assert(!serialize(clean).includes('bad.example'));assert.deepEqual(pack(roundTrip(clean,'css')),pack(clean));
""")

    def test_rect_default_preserves_direct_css_and_inherited_fill(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg"><style>.painted {fill:rebeccapurple} .direct > rect {fill:rgb(10 20 30 / 50%)}</style>
<rect id="missing"/><rect id="explicit" fill="none"/><g fill="#456"><rect id="inherited-attribute"/></g><g style="fill:#678"><rect id="inherited-style"/></g><g class="painted"><rect id="inherited-rule"/></g><g class="direct"><rect id="direct-rule"/></g><rect id="inline" style="fill:#987"/></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'paint'),rects=nodes(clean,'rect');
assert.equal(rects[0].getAttribute('fill'),'#ffffff');assert.equal(rects[1].getAttribute('fill'),'none');
for(const rect of rects.slice(2))assert.equal(rect.hasAttribute('fill'),false);
assert.deepEqual(pack(roundTrip(clean,'paint')),pack(clean));
""")

    def test_invalid_color_names_css_wide_resets_and_invalid_functions_get_safe_fill(self):
        values = ['notacolor', 'initial', 'inherit', 'unset', 'revert', 'revert-layer', 'rgb()', 'rgb(1 2 3 4)', 'rgb(10,20%,30)', 'rgba(1,2,3,invalid)', 'hsl(10,20,30)', 'rgb(1e9999 0 0)']
        source = '<svg xmlns="http://www.w3.org/2000/svg"><style>.invalid{fill:notacolor}.reset{fill:initial}.reset-again{fill:unset}</style>' + ''.join('<rect fill="' + value + '"/>' for value in values) + '<rect class="invalid"/><rect class="reset"/><rect class="reset-again"/><rect fill="none"/><rect fill="transparent"/><rect fill="black"/><g fill="teal"><rect fill="inherit"/></g></svg>'
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'invalid'),rects=nodes(clean,'rect');
for(const rect of rects.slice(0,-4))assert.equal(rect.getAttribute('fill'),'#ffffff');
assert.equal(rects.at(-4).getAttribute('fill'),'none');assert.equal(rects.at(-3).getAttribute('fill'),'transparent');assert.equal(rects.at(-2).getAttribute('fill'),'black');
assert.equal(rects.at(-1).getAttribute('fill'),null);assert.equal(rects.at(-1).parentNode.getAttribute('fill'),'teal');
assert.deepEqual(pack(roundTrip(clean,'invalid')),pack(clean));
""")

    def test_current_color_requires_concrete_authored_color_and_respects_cascade(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg"><style>.unknown{fill:currentColor!important}.known{fill:currentColor;color:rebeccapurple}.known-child{color:rgba(10,20,30,.5)}.overridden{fill:currentColor!important}.concrete{fill:teal!important}#priority{fill:currentColor}</style>
<rect fill="currentColor"/><rect class="unknown" fill="#fff"/><rect class="known"/><g color="navy"><rect fill="currentColor"/></g><g fill="currentColor"><rect class="known-child"/></g><rect class="overridden" style="fill:green"/><rect class="unknown" style="fill:green!important"/><rect class="concrete" fill="currentColor"/><rect id="priority" class="known"/><rect style="fill:currentColor;color:initial"/></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'current'),rects=nodes(clean,'rect');
for(const index of [0,1,5,9])assert(rects[index].getAttribute('style').endsWith('fill:#ffffff!important'));
for(const index of [2,3,4,7,8])assert(!rects[index].getAttribute('style')?.includes('#ffffff'));
assert.equal(rects[6].getAttribute('style'),'fill:green!important');
const twice=roundTrip(clean,'current');assert.deepEqual(pack(twice),pack(clean));assert.deepEqual(pack(roundTrip(twice,'current')),pack(clean));
""")

    def test_recognized_color_forms_and_namespaced_id_selectors_preserve_paint(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg" id="canvas"><style>svg#canvas #box{fill:rgb(10 20 30 / 50%)} #canvas .hue{fill:hsl(0.5turn 30% 40% / .8)}</style><rect id="box"/><rect class="hue"/><rect fill="RebeccaPurple"/><rect fill="#1234"/><rect fill="rgba(10%,20%,30%,40%)"/></svg>'''
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'scoped'),rects=nodes(clean,'rect');
assert.equal(rects[0].getAttribute('fill'),null);assert.equal(rects[1].getAttribute('fill'),null);
assert.equal(rects[2].getAttribute('fill'),'RebeccaPurple');assert.equal(rects[3].getAttribute('fill'),'#1234');assert.equal(rects[4].getAttribute('fill'),'rgba(10%,20%,30%,40%)');
assert.deepEqual(pack(roundTrip(clean,'scoped')),pack(clean));
""")

    def test_namespaces_local_references_and_css_are_deterministic_and_isolated(self):
        source = '''<svg xmlns="http://www.w3.org/2000/svg" id="diagram"><style>#diagram{color:navy} #diagram .node{fill:#fff} #box{stroke:red} .node > rect{stroke-width:2}</style><defs><linearGradient id="gradient"><stop offset="0%" stop-color="#abc"/><stop offset="100%" stop-color="#def"/></linearGradient><marker id="arrow"/></defs><g class="node"><rect id="box" fill="url('#gradient')" marker-end="url(#arrow)" clip-path="url(#outside)"/></g></svg>'''
        self.run_js([source], r"""
const one=PortalSvg.sanitize(sources[0],'one'),two=PortalSvg.sanitize(sources[0],'two');
const ids=root=>nodes(root).map(node=>node.getAttribute('id')).filter(Boolean),first=ids(one),second=ids(two);
assert.equal(new Set([...first,...second]).size,first.length+second.length);
assert.equal(nodes(one,'rect')[0].getAttribute('clip-path'),null);
assert(nodes(one,'rect')[0].getAttribute('fill').includes(nodes(one,'linearGradient')[0].getAttribute('id')));
assert.deepEqual(pack(roundTrip(one,'one')),pack(one));assert.deepEqual(pack(PortalSvg.sanitize(sources[0],'one')),pack(one));
""")

    def test_parser_failure_unsupported_root_and_duplicate_ids_throw(self):
        sources = ['<svg><g></svg>', '<svg/>', '<svg xmlns="urn:other"/>', '<html xmlns="http://www.w3.org/1999/xhtml"/>', '<svg xmlns="http://www.w3.org/2000/svg"><rect id="same"/><g id="same"/></svg>', '<svg xmlns="http://www.w3.org/2000/svg"><rect id="portal-svg-error-root"/></svg>']
        self.run_js(sources, r"""
for(const source of sources)assert.throws(()=>PortalSvg.sanitize(source,'error'),/SVG/);
assert.throws(()=>PortalSvg.sanitize(sources[0],'bad namespace'),/namespace/);
assert.throws(()=>PortalSvg.sanitize('','error'),/empty/);
assert.throws(()=>PortalSvg.sanitize('<!DOCTYPE svg [<!ENTITY x "test">]><svg/>','error'),/declarations/);
assert.throws(()=>PortalSvg.sanitize('<?xml-stylesheet href="https://bad.example/x"?><svg/>','error'),/instructions/);
const parser=globalThis.DOMParser;delete globalThis.DOMParser;assert.throws(()=>PortalSvg.sanitize(sources[0],'error'),/unavailable/);globalThis.DOMParser=parser;
""")

    def test_long_identifiers_round_trip_and_safe_css_is_scoped(self):
        source = '<svg xmlns="http://www.w3.org/2000/svg"><rect id="' + 'x' * 256 + '"/></svg>'
        self.run_js([source], r"""
const clean=PortalSvg.sanitize(sources[0],'long');assert.deepEqual(pack(roundTrip(clean,'long')),pack(clean));
const css=PortalSvg.safeCss('svg {fill:#fff}.node rect{stroke:#123;position:fixed}a{fill:red}', 'only');
assert.equal(css,'#portal-svg-only-root{fill:#fff}\n#portal-svg-only-root .node rect{stroke:#123}');
assert.equal(PortalSvg.safeCss(css,'only'),css);
assert.throws(()=>PortalSvg.safeCss('#x{fill:red}','only',{x:'outside'}),/namespaced/);
""")


if __name__ == '__main__':
    unittest.main()
