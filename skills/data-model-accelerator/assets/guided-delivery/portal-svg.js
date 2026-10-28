/* Detached, allowlisted SVG reconstruction for the offline review portal. */
(function (global) {
  'use strict';
  const SVG = 'http://www.w3.org/2000/svg';
  const ELEMENTS = new Set(['svg','g','rect','path','line','polyline','polygon','circle','ellipse','text','tspan','title','desc','defs','marker','style','clipPath','mask','linearGradient','radialGradient','stop']);
  const TEXT_ELEMENTS = new Set(['text','tspan','title','desc']);
  const NUMBER = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?';
  const LENGTH = new RegExp('^' + NUMBER + '(?:px|pt|pc|em|ex|rem|%|cm|mm|in)?$');
  const NUMBERS = new RegExp('^' + NUMBER + '(?:[ ,]+' + NUMBER + ')*$');
  const IDENT = /^[A-Za-z_][A-Za-z0-9_-]*$/;
  const GEOMETRY = new Set(['x','y','x1','y1','x2','y2','width','height','rx','ry','cx','cy','r','dx','dy','refX','refY','markerWidth','markerHeight','offset','fx','fy','fr']);
  const ENUMS = {
    'stroke-linecap':['butt','round','square'], 'stroke-linejoin':['miter','round','bevel'],
    'fill-rule':['nonzero','evenodd'], 'clip-rule':['nonzero','evenodd'],
    'font-style':['normal','italic','oblique'], 'font-variant':['normal','small-caps'],
    'text-anchor':['start','middle','end'], 'dominant-baseline':['auto','middle','central','hanging','alphabetic','text-before-edge','text-after-edge'],
    'alignment-baseline':['auto','baseline','middle','central','hanging','alphabetic','before-edge','after-edge'],
    'visibility':['visible','hidden','collapse'], 'display':['inline','block','none'],
    'vector-effect':['none','non-scaling-stroke'], 'shape-rendering':['auto','optimizeSpeed','crispEdges','geometricPrecision'],
    'text-rendering':['auto','optimizeSpeed','optimizeLegibility','geometricPrecision']
  };
  const PAINT = new Set(['fill','stroke','color','stop-color']);
  const COLORS = new Set(('aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen transparent').split(' '));
  const RESOURCES = new Set(['marker-start','marker-mid','marker-end','clip-path','mask']);
  const OPACITY = new Set(['opacity','fill-opacity','stroke-opacity','stop-opacity']);
  const DIMENSIONS = new Set(['stroke-width','font-size','letter-spacing','word-spacing','stroke-dashoffset']);

  function context(namespace, ids) {
    if (typeof namespace !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(namespace)) throw new Error('SVG namespace must be a short, unique identifier.');
    return {rootId:'portal-svg-' + namespace + '-root', prefix:'portal-svg-' + namespace + '-id-', ids:ids || new Map()};
  }
  function localReference(value, ctx) {
    const match = /^url\(\s*['"]?#([^\s'"()]+)['"]?\s*\)$/i.exec(value);
    return match && ctx.ids.has(match[1]) ? 'url(#' + ctx.ids.get(match[1]) + ')' : null;
  }
  function color(value, name) {
    const lowered = value.toLowerCase();
    if (COLORS.has(lowered) || lowered === 'currentcolor' || lowered === 'none' && ['fill','stroke'].includes(name) || /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value)) return value;
    const call = /^(rgb|rgba|hsl|hsla)\(([^()]*)\)$/i.exec(value);
    if (!call) return null;
    const legacy = call[2].includes(','), split = legacy ? call[2].split(',').map(part=>part.trim()) : call[2].split('/').map(part=>part.trim());
    if (legacy && (split.length < 3 || split.length > 4) || !legacy && split.length > 2) return null;
    const channels = legacy ? split.slice(0,3) : split[0].split(/\s+/), alpha = legacy ? split[3] : split[1];
    const numeric = (part, suffix='')=>new RegExp('^' + NUMBER + suffix + '$').test(part) && Number.isFinite(parseFloat(part));
    if (channels.length !== 3 || alpha !== undefined && !numeric(alpha, '%?')) return null;
    if (/^rgb/i.test(call[1])) {
      if (!channels.every(part=>numeric(part, '%?')) || legacy && channels.some(part=>part.endsWith('%')) && !channels.every(part=>part.endsWith('%'))) return null;
    } else if (!numeric(channels[0], '(?:deg|grad|rad|turn)?') || !channels.slice(1).every(part=>numeric(part, '%'))) return null;
    return value;
  }
  function propertyValue(name, raw, ctx) {
    const value = String(raw).trim();
    if (!value || value.length > 2048 || /[\\<>@;{}\x00-\x1f\x7f]/.test(value)) return null;
    if (PAINT.has(name)) return (['fill','stroke'].includes(name) ? localReference(value, ctx) : null) || color(value, name);
    if (RESOURCES.has(name)) return value === 'none' ? value : localReference(value, ctx);
    if (OPACITY.has(name)) return /^(?:\d+(?:\.\d*)?|\.\d+)%?$/.test(value) ? value : null;
    if (DIMENSIONS.has(name)) return LENGTH.test(value) || name === 'font-size' && /^(?:small|medium|large|smaller|larger)$/.test(value) ? value : null;
    if (name === 'stroke-dasharray') return value === 'none' || value.split(/[ ,]+/).every(part=>LENGTH.test(part)) ? value : null;
    if (name === 'stroke-miterlimit') return /^\d+(?:\.\d+)?$/.test(value) ? value : null;
    if (name === 'font-weight') return /^(?:normal|bold|bolder|lighter|[1-9]00)$/.test(value) ? value : null;
    if (name === 'font-family') return /^(?:[A-Za-z][A-Za-z0-9 -]*|'[A-Za-z][A-Za-z0-9 -]*'|"[A-Za-z][A-Za-z0-9 -]*")(?:\s*,\s*(?:[A-Za-z][A-Za-z0-9 -]*|'[A-Za-z][A-Za-z0-9 -]*'|"[A-Za-z][A-Za-z0-9 -]*"))*$/.test(value) ? value : null;
    return Object.hasOwn(ENUMS, name) && ENUMS[name].includes(value) ? value : null;
  }
  function declarations(source, ctx) {
    const result = [];
    if (typeof source !== 'string' || source.length > 250000 || /[\\\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(source)) return result;
    const cleaned = source.replace(/\/\*[\s\S]*?\*\//g, '');
    if (cleaned.includes('/*')) return result;
    for (const entry of cleaned.split(';')) {
      const split = entry.indexOf(':');
      if (split < 0) continue;
      const name = entry.slice(0, split).trim().toLowerCase();
      const raw = entry.slice(split + 1).trim(), important = /\s*!important\s*$/i.test(raw);
      const value = propertyValue(name, raw.replace(/\s*!important\s*$/i, ''), ctx);
      if (value !== null) result.push({name,value,important});
    }
    return result;
  }
  const declarationText = list => list.map(item=>item.name + ':' + item.value + (item.important ? '!important' : '')).join(';');
  function selector(source, ctx) {
    let value = source.trim().replace(/\s*>\s*/g, ' > ').replace(/\s+/g, ' ');
    if (!value || value.length > 1000 || /[^A-Za-z0-9_#. >-]/.test(value)) return null;
    const pieces = value.split(' ');
    if (pieces[0] === '>' || pieces.at(-1) === '>') return null;
    for (let i = 0; i < pieces.length; i++) {
      if (pieces[i] === '>') { if (pieces[i-1] === '>') return null; continue; }
      if (!/^(?:[A-Za-z][A-Za-z0-9_-]*)?(?:[.#][A-Za-z_][A-Za-z0-9_-]*)*$/.test(pieces[i])) return null;
      const tag = /^[A-Za-z][A-Za-z0-9_-]*/.exec(pieces[i]);
      if (tag && !ELEMENTS.has(tag[0])) return null;
      let unknown = false;
      pieces[i] = pieces[i].replace(/#([A-Za-z_][A-Za-z0-9_-]*)/g, (_, id)=>{
        if (!ctx.ids.has(id)) { unknown = true; return ''; }
        return '#' + ctx.ids.get(id);
      });
      if (unknown) return null;
    }
    const root = '#' + ctx.rootId;
    if (/^svg(?=[.#]|$)/.test(pieces[0])) {
      pieces[0] = pieces[0].replace(/^svg/, '');
      if (!pieces[0].includes(root)) pieces[0] = root + pieces[0];
    }
    value = pieces.join(' ');
    if (pieces[0] === root || pieces[0].startsWith(root + '.') || pieces[0].startsWith(root + '#')) return value;
    return root + ' ' + value;
  }
  function styleRules(source, ctx) {
    const rules = [];
    if (typeof source !== 'string' || source.length > 250000 || /[\\<\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(source)) return rules;
    const text = source.replace(/\/\*[\s\S]*?\*\//g, '');
    if (text.includes('/*')) return rules;
    let cursor = 0;
    while (cursor < text.length) {
      while (/\s/.test(text[cursor] || '') && cursor < text.length) cursor++;
      const start = cursor, open = text.indexOf('{', cursor), semi = text.indexOf(';', cursor);
      // At-rules never enter the output, including imports and nested styles.
      if (text[cursor] === '@' && semi >= 0 && (open < 0 || semi < open)) { cursor = semi + 1; continue; }
      if (open < 0) break;
      let depth = 1, close = open + 1, nested = false;
      while (close < text.length && depth) { if (text[close] === '{') { depth++; nested = true; } if (text[close] === '}') depth--; close++; }
      if (depth) break;
      cursor = close;
      if (text[start] === '@' || nested) continue;
      const selectors = text.slice(start, open).split(',').map(part=>selector(part, ctx)).filter(Boolean);
      const values = declarations(text.slice(open + 1, close - 1), ctx);
      if (selectors.length && values.length) rules.push({selectors,values});
    }
    return rules;
  }
  const rulesText = rules => rules.map(rule=>rule.selectors.join(',') + '{' + declarationText(rule.values) + '}').join('\n');
  function safeCss(source, namespace, ids) {
    const ctx = context(namespace, ids instanceof Map ? ids : new Map(Object.entries(ids || {})));
    for (const [original, mapped] of ctx.ids) {
      if (typeof original !== 'string' || typeof mapped !== 'string' || !IDENT.test(mapped) || !(mapped === ctx.rootId || mapped.startsWith(ctx.prefix))) throw new Error('SVG CSS references must use namespaced identifiers.');
    }
    ctx.ids.set(ctx.rootId, ctx.rootId);
    return rulesText(styleRules(source, ctx));
  }
  function simpleMatches(node, expression) {
    if (!node || node.nodeType !== 1) return false;
    const tag = /^[A-Za-z][A-Za-z0-9_-]*/.exec(expression);
    if (tag && node.localName !== tag[0]) return false;
    const classes = new Set((node.getAttribute('class') || '').split(/\s+/));
    return Array.from(expression.matchAll(/([.#])([A-Za-z_][A-Za-z0-9_-]*)/g)).every(([,kind,value])=>kind === '#' ? node.getAttribute('id') === value : classes.has(value));
  }
  function matches(node, expression) {
    const pieces = expression.split(' ');
    let i = pieces.length - 1, current = node;
    if (!simpleMatches(current, pieces[i--])) return false;
    while (i >= 0) {
      if (pieces[i] === '>') { current = current.parentNode; i--; if (!simpleMatches(current, pieces[i--])) return false; }
      else { current = current.parentNode; while (current && !simpleMatches(current, pieces[i])) current = current.parentNode; if (!current) return false; i--; }
    }
    return true;
  }
  function authoredPaint(node, name, rules, ctx) {
    let winner = node.hasAttribute(name) ? {value:node.getAttribute(name), rank:[0,0,0,0,0,-1]} : null;
    function consider(item, specificity, order) {
      if (item.name !== name) return;
      const rank = [item.important ? 1 : 0, ...specificity, order];
      const comparison = winner ? rank.findIndex((value,index)=>value !== winner.rank[index]) : -1;
      if (!winner || comparison >= 0 && rank[comparison] > winner.rank[comparison]) winner = {value:item.value,rank};
    }
    let order = 0;
    for (const rule of rules) {
      for (const expression of rule.selectors) {
        if (!matches(node, expression)) continue;
        const specificity = [0, (expression.match(/#/g)||[]).length, (expression.match(/\./g)||[]).length, expression.split(' ').filter(part=>/^[A-Za-z]/.test(part)).length];
        rule.values.forEach((item,index)=>consider(item,specificity,order + index));
      }
      order += rule.values.length;
    }
    declarations(node.getAttribute('style') || '', ctx).forEach((item,index)=>consider(item,[1,0,0,0],order + index));
    return winner?.value || null;
  }
  function concreteRectPaint(rect, rules, ctx) {
    let fill = null;
    for (let node = rect; node && fill === null; node = node.parentNode) fill = authoredPaint(node,'fill',rules,ctx);
    if (fill?.toLowerCase() !== 'currentcolor') return {fill,unresolvedCurrentColor:false};
    for (let node = rect; node; node = node.parentNode) {
      const value = authoredPaint(node,'color',rules,ctx);
      if (value && value.toLowerCase() !== 'currentcolor') return {fill:value,unresolvedCurrentColor:false};
    }
    return {fill:null,unresolvedCurrentColor:true};
  }
  function sanitize(svgText, namespace) {
    const ctx = context(namespace);
    if (typeof svgText !== 'string' || !svgText.trim() || svgText.length > 2 * 1024 * 1024) throw new Error('SVG text is empty or exceeds the inline size limit.');
    if (/<!\s*(?:DOCTYPE|ENTITY)\b|<\?|\x00/i.test(svgText)) throw new Error('SVG declarations and processing instructions are unsupported.');
    if (typeof global.DOMParser !== 'function') throw new Error('SVG XML parsing is unavailable.');
    let parsed;
    try { parsed = new global.DOMParser().parseFromString(svgText, 'image/svg+xml'); }
    catch { throw new Error('SVG XML could not be parsed.'); }
    const root = parsed?.documentElement;
    if (!root || root.localName !== 'svg' || root.namespaceURI !== SVG || parsed.getElementsByTagName('parsererror').length) throw new Error('SVG XML is malformed or has an unsupported root namespace.');
    const permitted = [], children = new Map();
    function inventory(node, depth) {
      if (node.nodeType !== 1 || node.namespaceURI !== SVG || !ELEMENTS.has(node.localName)) return;
      if (depth > 64 || permitted.length >= 20000) throw new Error('SVG structure exceeds the inline complexity limit.');
      permitted.push(node); children.set(node, []);
      for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === 1 && child.namespaceURI === SVG && ELEMENTS.has(child.localName)) { children.get(node).push(child); inventory(child, depth + 1); }
      }
    }
    inventory(root, 0);
    const outputIds = new Set([ctx.rootId]);
    for (const node of permitted) {
      const id = node.getAttribute('id');
      if (!id) continue;
      if (id.length > (id.startsWith(ctx.prefix) ? 2048 : 256) || /[\s\x00-\x1f\x7f]/.test(id) || ctx.ids.has(id)) throw new Error('SVG identifiers are invalid or duplicated.');
      if (node !== root && id === ctx.rootId) throw new Error('SVG identifier conflicts with the reserved root identifier.');
      let mapped = node === root ? ctx.rootId : id.startsWith(ctx.prefix) && /^[A-Za-z0-9_-]+$/.test(id) ? id : ctx.prefix + Array.from(id, char=>char.codePointAt(0).toString(16)).join('-');
      if (node !== root && outputIds.has(mapped)) throw new Error('SVG identifiers collide after namespacing.');
      outputIds.add(mapped); ctx.ids.set(id, mapped);
    }
    ctx.ids.set(ctx.rootId, ctx.rootId);
    const allRules = [], rects = [];
    function rebuild(node) {
      const result = global.document.createElementNS(SVG, node.localName);
      if (node === root) result.setAttribute('id', ctx.rootId);
      if (node.localName === 'style') {
        const rules = styleRules(node.textContent, ctx); allRules.push(...rules);
        result.textContent = rulesText(rules); return result;
      }
      for (const attribute of Array.from(node.attributes)) {
        const key = attribute.name, raw = attribute.value;
        if (attribute.namespaceURI || key.includes(':') || /^on/i.test(key)) continue;
        let value = null;
        if (key === 'id') value = ctx.ids.get(raw) || null;
        else if (key === 'class' && raw.length <= 1000 && raw.trim().split(/\s+/).every(part=>IDENT.test(part))) value = raw.trim().replace(/\s+/g, ' ');
        else if (key === 'style') value = declarationText(declarations(raw, ctx)) || null;
        else if (key === 'data-model-id' || key === 'data-model-name' || key === 'data-occurrence-id' || key === 'aria-label') value = raw.length <= 4096 ? raw : null;
        else if (key === 'role' && ['img','presentation'].includes(raw)) value = raw;
        else if (key === 'aria-hidden' && ['true','false'].includes(raw)) value = raw;
        else if (GEOMETRY.has(key) && LENGTH.test(raw)) value = raw;
        else if (key === 'viewBox' && raw.trim().split(/[ ,]+/).length === 4 && NUMBERS.test(raw.trim())) value = raw.trim();
        else if (key === 'points' && raw.length < 100000 && NUMBERS.test(raw.trim())) value = raw.trim();
        else if (key === 'd' && raw.length < 100000 && /^[MmZzLlHhVvCcSsQqTtAaEe0-9+.,\s-]+$/.test(raw)) value = raw;
        else if ((key === 'transform' || key === 'gradientTransform') && /^(?:(?:matrix|translate|scale|rotate|skewX|skewY)\([\d.eE+,\s-]+\)\s*)+$/.test(raw)) value = raw;
        else if (key === 'preserveAspectRatio' && /^(?:none|x(?:Min|Mid|Max)Y(?:Min|Mid|Max)(?:\s+(?:meet|slice))?)$/.test(raw)) value = raw;
        else if (key === 'orient' && (raw === 'auto' || raw === 'auto-start-reverse' || LENGTH.test(raw))) value = raw;
        else if (key === 'markerUnits' && ['strokeWidth','userSpaceOnUse'].includes(raw)) value = raw;
        else if (['gradientUnits','clipPathUnits','maskUnits','maskContentUnits'].includes(key) && ['userSpaceOnUse','objectBoundingBox'].includes(raw)) value = raw;
        else if (key === 'spreadMethod' && ['pad','reflect','repeat'].includes(raw)) value = raw;
        else value = propertyValue(key, raw, ctx);
        if (value !== null) result.setAttribute(key, value);
      }
      if (node.localName === 'rect') rects.push(result);
      for (const child of Array.from(node.childNodes)) {
        if (children.get(node).includes(child)) result.appendChild(rebuild(child));
        else if ((child.nodeType === 3 || child.nodeType === 4) && TEXT_ELEMENTS.has(node.localName)) result.appendChild(global.document.createTextNode(child.nodeValue));
      }
      return result;
    }
    const rebuilt = rebuild(root);
    // Only concrete authored paint counts; CSS-wide resets and invalid color
    // tokens cannot accidentally restore SVG's implicit black rectangle fill.
    for (const rect of rects) {
      const paint = concreteRectPaint(rect,allRules,ctx);
      if (paint.unresolvedCurrentColor) rect.setAttribute('style', (rect.getAttribute('style') ? rect.getAttribute('style') + ';' : '') + 'fill:#ffffff!important');
      else if (paint.fill === null) rect.setAttribute('fill', '#ffffff');
    }
    return rebuilt;
  }
  global.PortalSvg = Object.freeze({sanitize,safeCss});
})(globalThis);
