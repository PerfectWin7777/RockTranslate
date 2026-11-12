/**
 * RockTranslate — Reader features
 * Path: src/rocktranslate/assets/ui/js/reader.js
 *
 * Makes the workspace a daily PDF reader:
 *  - selection toolbar + streaming bubble (translate / explain / clean copy /
 *    copy with citation / highlight), custom context menu;
 *  - previews of internal links (citations, figures, tables, equations) with
 *    "open & translate" for arXiv references;
 *  - snapshot of an area or a page to the clipboard (original or translation);
 *  - night reading that keeps figures intact, hold Alt to see the original;
 *  - continuous translation of the pages being read, resume where you left;
 *  - highlights and notes; document tabs; command palette and shortcuts.
 *
 * The two panes are same-origin iframes: the original (PDF.js, left) and the
 * translated layout (pdf2htmlEX, right). Handlers are attached to each frame
 * document once (polling, since the workspace is re-mounted per document).
 *
 * Author: RockTranslate Contributors
 * License: MIT License
 */
(function () {
    'use strict';

    // ── Shared helpers ───────────────────────────────────────────────────────
    const RT = window.RT = {
        pdfFrame: () => document.getElementById('pdf-iframe'),
        htmlFrame: () => document.getElementById('html-iframe'),
        app() {
            try { return RT.pdfFrame().contentWindow.PDFViewerApplication || null; } catch (e) { return null; }
        },
        api: () => (window.pywebview && window.pywebview.api) || null,
        t: (key, vars) => Alpine.store('i18n').translate(key, vars || {}),
        toast: (msg, type, ms) => window.showToast && window.showToast(msg, type || 'info', ms || 3500),
        store: () => Alpine.store('reader'),
        docOpen: () => !!document.getElementById('pdf-iframe') && Alpine.store('reader') && !!Alpine.store('reader').activePath,
        esc: (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
    };

    /**
     * Minimal, safe Markdown for model answers: the text is HTML-escaped
     * FIRST, then only these forms are rebuilt: headings, '- ' / '1.' lists,
     * **bold**, *italic*, `code`, paragraphs and line breaks. Nothing from
     * the model is ever inserted as raw HTML.
     */
    RT.md = function (text) {
        const inline = (s) => s
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
        const lines = RT.esc(String(text || '')).replace(/\r/g, '').split('\n');
        const out = []; let list = null; let para = [];
        const flushPara = () => { if (para.length) { out.push('<p>' + inline(para.join('<br>')) + '</p>'); para = []; } };
        const flushList = () => { if (list) { out.push(`<${list.tag}>` + list.items.map((i) => '<li>' + inline(i) + '</li>').join('') + `</${list.tag}>`); list = null; } };
        lines.forEach((raw) => {
            const line = raw.trim();
            let m;
            if (!line) { flushPara(); flushList(); return; }
            if ((m = /^(#{1,4})\s+(.*)$/.exec(line))) { flushPara(); flushList(); out.push(`<h${Math.min(6, m[1].length + 3)}>${inline(m[2])}</h${Math.min(6, m[1].length + 3)}>`); return; }
            if ((m = /^[-*•]\s+(.*)$/.exec(line)) || (m = /^\d+[.)]\s+(.*)$/.exec(line))) {
                flushPara();
                const tag = /^\d/.test(line) ? 'ol' : 'ul';
                if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
                list.items.push(m[1]); return;
            }
            if (list && /^\s{2,}/.test(raw)) { list.items[list.items.length - 1] += ' ' + line; return; }
            flushList(); para.push(line);
        });
        flushPara(); flushList();
        return out.join('');
    };

    // Toast with the thumbnail of the image just copied
    RT.imageToast = function (dataUrl, message) {
        let el = document.getElementById('rt-image-toast');
        if (!el) {
            el = document.createElement('div'); el.id = 'rt-image-toast'; el.className = 'rt-pop';
            el.innerHTML = '<img alt=""><span></span>';
            el.addEventListener('click', () => el.classList.remove('show'));
            document.body.appendChild(el);
        }
        el.querySelector('img').src = dataUrl;
        el.querySelector('span').textContent = message;
        el.classList.add('show');
        clearTimeout(el._timer);
        el._timer = setTimeout(() => el.classList.remove('show'), 4000);
    };

    function pref(key, fallback) {
        try { const v = localStorage.getItem('rt-reader-' + key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
    }
    function setPref(key, value) {
        try { localStorage.setItem('rt-reader-' + key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    }

    // ── Global reader state (survives the per-document workspace re-mount) ─
    document.addEventListener('alpine:init', () => {
        Alpine.store('reader', {
            panelOpen: pref('panel', false),
            panelTab: pref('panelTab', 'toc'),
            night: pref('night', false),
            continuous: pref('continuous', false),
            layout: 'both',
            tabs: [],            // [{path, name}]
            activePath: null,
            currentPage: 1,
            highlights: [],
            translateRefs: true,
            togglePanel(tab) {
                if (tab && (!this.panelOpen || this.panelTab !== tab)) { this.panelOpen = true; this.panelTab = tab; }
                else this.panelOpen = !this.panelOpen;
                setPref('panel', this.panelOpen); setPref('panelTab', this.panelTab);
                setTimeout(() => { try { RT.pdfFrame().contentWindow.dispatchEvent(new Event('resize')); } catch (e) { } }, 60);
            },
        });
    });

    // ── "Translate the references" (same setting as Preferences > Translation) ─
    RT.refreshReferencesSetting = async function () {
        try { const p = await RT.api().get_preferences(); RT.store().translateRefs = p.translate_references !== false; } catch (e) { }
    };
    RT.toggleReferences = async function () {
        const on = !RT.store().translateRefs;
        RT.store().translateRefs = on;
        try { await RT.api().set_preference('translate_references', on); } catch (e) { }
        RT.toast(RT.t('rd_translate_refs_menu') + (on ? ' ✓' : ' ✗'), 'info', 2500);
    };
    document.addEventListener('alpine:initialized', () => {
        if (window.rtBridge) rtBridge.whenReady(() => RT.refreshReferencesSetting());
    });

    // ── Assistant requests (answers stream from Python) ─────────────────────
    const pending = {};
    window.rtAssistDelta = (id, text) => { const r = pending[id]; if (r && r.onDelta) r.onDelta(text); };
    window.rtAssistDone = (id, payload) => {
        const r = pending[id]; delete pending[id];
        if (!r) return;
        if (payload && !payload.ok && payload.error === 'no_key') RT.toast(RT.t('rd_no_key'), 'error', 6000);
        if (r.onDone) r.onDone(payload || { ok: false });
    };
    RT.request = function (start, onDelta, onDone) {
        const id = 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        pending[id] = { onDelta, onDone };
        Promise.resolve().then(() => start(id)).catch((e) => window.rtAssistDone(id, { ok: false, error: String(e) }));
        return id;
    };
    RT.assist = (mode, text, onDelta, onDone, extra) =>
        RT.request((id) => RT.api().assist_start(mode, text, id, extra || {}), onDelta, onDone);

    // ── Clipboard ────────────────────────────────────────────────────────────
    RT.copyText = async function (text) {
        try { await navigator.clipboard.writeText(text); }
        catch (e) {
            const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
            ta.select(); document.execCommand('copy'); ta.remove();
        }
        RT.toast(RT.t('rd_copied'), 'success', 1800);
    };
    RT.copyImage = async function (canvasOrDataUrl, name) {
        const dataUrl = typeof canvasOrDataUrl === 'string' ? canvasOrDataUrl : canvasOrDataUrl.toDataURL('image/png');
        try {
            const blob = await (await fetch(dataUrl)).blob();
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
            RT.imageToast(dataUrl, RT.t('rd_img_copied'));
        } catch (e) {
            // Clipboard refused (permissions): save the PNG instead
            const res = await RT.api().save_png_file(dataUrl, name || 'rocktranslate.png');
            if (res && res.status === 'success') RT.imageToast(dataUrl, RT.t('rd_img_saved', { path: res.path }));
        }
    };

    // ── Selection model ──────────────────────────────────────────────────────
    let selection = null;   // {text, side: 'original'|'translation', rect (main coords), pageNumber, rects}

    function frameOf(doc) {
        const pf = RT.pdfFrame(), hf = RT.htmlFrame();
        if (pf && pf.contentDocument === doc) return { frame: pf, side: 'original' };
        if (hf && hf.contentDocument === doc) return { frame: hf, side: 'translation' };
        return null;
    }

    // Element rect inside a frame -> main window coordinates
    function toMain(frame, r) {
        const fr = frame.getBoundingClientRect();
        return { left: fr.left + r.left, top: fr.top + r.top, right: fr.left + r.right, bottom: fr.top + r.bottom,
                 width: r.width, height: r.height };
    }

    // Union of the visible line boxes: the range's own box can include
    // invisible helpers of the text layer (PDF.js "endOfContent").
    function rangeBox(range) {
        const boxes = Array.from(range.getClientRects()).filter((x) => x.width > 0.5 && x.height > 0.5 && x.height < 120);
        if (!boxes.length) return null;
        const r = { left: Math.min(...boxes.map((x) => x.left)), top: Math.min(...boxes.map((x) => x.top)),
                    right: Math.max(...boxes.map((x) => x.right)), bottom: Math.max(...boxes.map((x) => x.bottom)) };
        r.width = r.right - r.left; r.height = r.bottom - r.top;
        return r;
    }

    // Current position of a selection (the pane may have scrolled since)
    function freshRect(sel) {
        try { const r = rangeBox(sel.range); if (r) return toMain(sel.frame, r); } catch (e) { }
        return sel.rect;
    }

    function readSelection(doc) {
        const info = frameOf(doc);
        if (!info) return null;
        const sel = doc.getSelection();
        if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
        const text = sel.toString();
        if (!text || text.trim().length < 2) return null;
        const range = sel.getRangeAt(0);
        const r = rangeBox(range);
        if (!r) return null;
        const page = (range.startContainer.parentElement || range.startContainer).closest &&
            (range.startContainer.parentElement || range.startContainer).closest('.page, .pf');
        let pageNumber = null;
        if (page) {
            if (page.dataset.pageNumber) pageNumber = parseInt(page.dataset.pageNumber, 10);
            else { const m = /pf([0-9a-f]+)/i.exec(page.id || ''); if (m) pageNumber = parseInt(m[1], 16); }
        }
        return { text, side: info.side, frame: info.frame, rect: toMain(info.frame, r), pageNumber, range, pageEl: page };
    }

    // ── Floating toolbar ─────────────────────────────────────────────────────
    let toolbar = null;
    function buildToolbar() {
        toolbar = document.createElement('div');
        toolbar.id = 'rt-seltool';
        toolbar.className = 'rt-pop';
        toolbar.innerHTML = [
            ['translate', '文A', 'rd_translate', 'Ctrl+T'], ['explain', '?', 'rd_explain', 'Ctrl+E'],
            ['copy', '⧉', 'rd_copy', ''], ['cite', '❝', 'rd_copy_cite', ''], ['highlight', '▍', 'rd_highlight', 'Ctrl+H'],
        ].map(([act, icon, key, sc]) => `<button type="button" data-act="${act}" data-key="${key}" title="${sc}">` +
            `<span class="rt-ico">${icon}</span><span class="rt-lbl"></span></button>`).join('');
        toolbar.addEventListener('mousedown', (e) => e.preventDefault());   // keep the selection
        toolbar.addEventListener('click', (e) => {
            const b = e.target.closest('button'); if (!b) return;
            runOnSelection(b.dataset.act);
        });
        document.body.appendChild(toolbar);
    }
    function showToolbar(sel) {
        if (!toolbar) buildToolbar();
        toolbar.querySelectorAll('button').forEach((b) => {
            b.querySelector('.rt-lbl').textContent = RT.t(b.dataset.key);
            b.style.display = (b.dataset.act === 'highlight' && sel.side !== 'original') ? 'none' : '';
        });
        toolbar.style.display = 'flex';
        const w = toolbar.offsetWidth, h = toolbar.offsetHeight;
        let top = sel.rect.top - h - 8;
        if (top < 40) top = sel.rect.bottom + 8;
        top = Math.min(Math.max(40, top), window.innerHeight - h - 8);
        const left = Math.min(Math.max(8, sel.rect.left + sel.rect.width / 2 - w / 2), window.innerWidth - w - 8);
        toolbar.style.left = left + 'px'; toolbar.style.top = top + 'px';
    }
    function hideToolbar() { if (toolbar) toolbar.style.display = 'none'; }

    async function runOnSelection(act, sel) {
        sel = sel || selection;
        if (!sel) { RT.toast(RT.t('rd_select_first'), 'info'); return; }
        hideToolbar(); hideMenu();
        if (act === 'translate' || act === 'explain') openBubble(act, sel);
        else if (act === 'copy') RT.copyText(await RT.api().clean_text(sel.text));
        else if (act === 'cite') {
            const clean = await RT.api().clean_text(sel.text);
            const c = await RT.api().get_doc_citation();
            const where = sel.pageNumber ? `, p. ${sel.pageNumber}` : '';
            const ref = c && c.short ? ` (${c.short}${where})` : (where ? ` (${where.slice(2)})` : '');
            RT.copyText(`“${clean}”${ref}${c && c.doi ? ` https://doi.org/${c.doi}` : ''}`);
        } else if (act === 'highlight') addHighlight(sel);
    }

    // ── Bubble (streamed answer) ─────────────────────────────────────────────
    let bubble = null, bubbleReq = null;
    function buildBubble() {
        bubble = document.createElement('div');
        bubble.id = 'rt-bubble';
        bubble.className = 'rt-pop';
        bubble.innerHTML = `
            <div class="rt-bubble-head">
                <button type="button" data-mode="translate"></button>
                <button type="button" data-mode="explain"></button>
                <span class="rt-grow"></span>
                <button type="button" class="rt-icon-btn" data-act="regen" title="">↻</button>
                <button type="button" class="rt-icon-btn" data-act="copy" title="">⧉</button>
                <button type="button" class="rt-icon-btn" data-act="close" title="">✕</button>
            </div>
            <div class="rt-bubble-src"></div>
            <div class="rt-bubble-body"></div>
            <div class="rt-bubble-foot"></div>`;
        bubble.querySelector('.rt-bubble-head').addEventListener('mousedown', startDrag);
        bubble.addEventListener('click', (e) => {
            const b = e.target.closest('button'); if (!b) return;
            if (b.dataset.mode && bubble._sel) openBubble(b.dataset.mode, bubble._sel, true);
            else if (b.dataset.act === 'regen' && bubble._sel) openBubble(bubble._mode || 'translate', bubble._sel, true, true);
            else if (b.dataset.act === 'close') closeBubble();
            else if (b.dataset.act === 'copy') RT.copyText(bubble.querySelector('.rt-bubble-body').innerText);
        });
        document.body.appendChild(bubble);
    }
    function startDrag(e) {
        if (e.target.closest('button')) return;
        const r = bubble.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
        const move = (ev) => { bubble.style.left = (ev.clientX - dx) + 'px'; bubble.style.top = (ev.clientY - dy) + 'px'; };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
        document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    }
    function closeBubble() { if (bubble) bubble.style.display = 'none'; bubbleReq = null; }

    // Answers already received in this session, per (mode, selected text):
    // switching Translate <-> Explain shows them again without a new request.
    const bubbleCache = new Map();

    async function openBubble(mode, sel, keepPosition, force) {
        if (!bubble) buildBubble();
        bubble._sel = sel; bubble._mode = mode;
        // The answer language is part of the cache key: after switching the
        // target language, the same selection is asked again
        let lang = '';
        try { lang = (await RT.api().get_target_language()) || ''; } catch (e) { }
        bubble.querySelector('[data-mode="translate"]').textContent = RT.t('rd_translate');
        bubble.querySelector('[data-mode="explain"]').textContent = RT.t('rd_explain');
        bubble.querySelector('[data-act="copy"]').title = RT.t('rd_copy_answer');
        bubble.querySelector('[data-act="regen"]').title = RT.t('rd_regenerate');
        bubble.querySelector('[data-act="close"]').title = RT.t('rd_close');
        bubble.querySelectorAll('[data-mode]').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
        const src = sel.text.replace(/\s+/g, ' ').trim();
        bubble.querySelector('.rt-bubble-src').textContent = src.length > 160 ? src.slice(0, 160) + '…' : src;
        const body = bubble.querySelector('.rt-bubble-body');
        const foot = bubble.querySelector('.rt-bubble-foot');
        body.textContent = ''; body.classList.add('rt-typing');
        foot.textContent = RT.t('rd_working');
        bubble.style.display = 'flex';
        if (!keepPosition) {
            const w = Math.min(480, window.innerWidth - 24);
            const rect = freshRect(sel);
            bubble.style.width = w + 'px';
            let top = rect.bottom + 10;
            if (top + 260 > window.innerHeight) top = rect.top - 270;
            top = Math.min(Math.max(44, top), window.innerHeight - 220);   // always on screen
            bubble.style.left = Math.min(Math.max(10, rect.left), window.innerWidth - w - 10) + 'px';
            bubble.style.top = top + 'px';
        }
        const cacheKey = mode + '\u0000' + lang + '\u0000' + sel.text;
        if (force) bubbleCache.delete(cacheKey);
        if (bubbleCache.has(cacheKey)) {
            const hit = bubbleCache.get(cacheKey);
            body.classList.remove('rt-typing');
            body.innerHTML = RT.md(hit.text); foot.textContent = hit.foot;
            bubbleReq = null;
            return;
        }
        const started = performance.now();
        let first = 0;
        let raw = '';
        const reqId = RT.assist(mode, sel.text, (piece) => {
            if (bubbleReq !== reqId) return;
            if (!first) first = performance.now();
            raw += piece;
            body.innerHTML = RT.md(raw);
        }, (res) => {
            if (bubbleReq !== reqId) return;
            body.classList.remove('rt-typing');
            if (!res.ok) { foot.textContent = RT.t('rd_error', { error: res.error || '?' }); return; }
            if (!raw) { raw = res.text || ''; body.innerHTML = RT.md(raw); }
            const secs = ((performance.now() - started) / 1000).toFixed(1);
            const firstMs = first ? Math.round(first - started) : null;
            const cost = window.rtShowCost !== false && res.cost ? ` · ~$${Number(res.cost).toFixed(4)}` : '';
            foot.textContent = `${(res.model || '').split('/').pop()} · ${secs} s${firstMs ? ` (${RT.t('rd_first_word', { ms: firstMs })})` : ''}${cost}`;
            if (bubbleCache.size > 200) bubbleCache.delete(bubbleCache.keys().next().value);
            bubbleCache.set(cacheKey, { text: raw, foot: foot.textContent });
        });
        bubbleReq = reqId;
    }

    // ── Context menu (right click in either pane) ───────────────────────────
    let menu = null;
    function hideMenu() { if (menu) menu.style.display = 'none'; }
    function showMenu(x, y, items) {
        if (!menu) {
            menu = document.createElement('div'); menu.id = 'rt-ctxmenu'; menu.className = 'rt-pop';
            menu.addEventListener('mousedown', (e) => e.preventDefault());
            menu.addEventListener('click', (e) => {
                const it = e.target.closest('[data-i]'); if (!it) return;
                const fn = menu._items[+it.dataset.i].run; hideMenu(); fn();
            });
            document.body.appendChild(menu);
        }
        menu._items = items;
        menu.innerHTML = items.map((it, i) => it.sep ? '<div class="rt-sep"></div>' :
            `<div class="rt-menu-item${it.disabled ? ' disabled' : ''}" data-i="${it.disabled ? '' : i}">` +
            `<span>${RT.esc(it.label)}</span><span class="rt-sc">${RT.esc(it.sc || '')}</span></div>`).join('');
        menu.style.display = 'block';
        menu.style.left = Math.min(x, window.innerWidth - menu.offsetWidth - 6) + 'px';
        menu.style.top = Math.min(y, window.innerHeight - menu.offsetHeight - 6) + 'px';
    }
    function contextItems(sel, side, pageNumber) {
        const items = [];
        if (sel) {
            items.push({ label: RT.t('rd_translate'), sc: 'Ctrl+T', run: () => runOnSelection('translate', sel) });
            items.push({ label: RT.t('rd_explain'), sc: 'Ctrl+E', run: () => runOnSelection('explain', sel) });
            items.push({ label: RT.t('rd_copy'), sc: 'Ctrl+C', run: () => runOnSelection('copy', sel) });
            items.push({ label: RT.t('rd_copy_cite'), run: () => runOnSelection('cite', sel) });
            if (side === 'original') items.push({ label: RT.t('rd_highlight'), sc: 'Ctrl+H', run: () => runOnSelection('highlight', sel) });
            items.push({ sep: true });
        }
        items.push({ label: RT.t('rd_snapshot'), sc: 'Ctrl+Shift+S', run: () => startSnapshot(side) });
        if (side === 'original') items.push({ label: RT.t('rd_page_image'), run: () => copyOriginalPage(pageNumber) });
        else items.push({ label: RT.t('rd_trans_page_image'), run: () => copyTranslatedPage(pageNumber) });
        if (pageNumber) items.push({ label: RT.t('rd_translate_page') + ` (${pageNumber})`, run: () => translatePages([pageNumber - 1], true) });
        return items;
    }

    // ── Attach to the two frames ─────────────────────────────────────────────
    function pageAt(doc, target) {
        const el = target && target.closest ? target.closest('.page, .pf') : null;
        if (!el) return RT.store().currentPage;
        if (el.dataset.pageNumber) return parseInt(el.dataset.pageNumber, 10);
        const m = /pf([0-9a-f]+)/i.exec(el.id || ''); return m ? parseInt(m[1], 16) : RT.store().currentPage;
    }

    function attach(doc) {
        if (!doc || doc.__rtReader) return;
        const info = frameOf(doc); if (!info) return;
        doc.__rtReader = true;
        const side = info.side;

        doc.addEventListener('mouseup', (e) => {
            if (e.button !== 0) return;
            setTimeout(() => {
                const sel = readSelection(doc);
                selection = sel;
                if (sel) showToolbar(sel); else hideToolbar();
            }, 10);
        });
        doc.addEventListener('mousedown', (e) => { if (e.button === 0) { hideToolbar(); hideMenu(); } });
        doc.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            const sel = readSelection(doc);
            if (sel) selection = sel;
            const fr = info.frame.getBoundingClientRect();
            showMenu(fr.left + e.clientX, fr.top + e.clientY, contextItems(sel, side, pageAt(doc, e.target)));
        });
        // Clean copy: no line breaks nor end-of-line hyphens in what is pasted
        doc.addEventListener('copy', (e) => {
            const text = doc.getSelection().toString();
            if (!text || !pref('cleanCopy', true)) return;
            const clean = text.replace(/­/g, '').replace(/(\w)-\s*\n\s*(\w)/g, '$1$2')
                .split(/\n\s*\n/).map((p) => p.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n\n');
            e.clipboardData.setData('text/plain', clean);
            e.preventDefault();
        });
        // Keys typed in a pane reach the shortcuts (the workspace forwards a clone
        // which cannot prevent the frame's own default: done here for ours)
        doc.addEventListener('keydown', (e) => { if (shortcutFor(e)) e.preventDefault(); }, true);
        doc.addEventListener('keyup', (e) => { if (e.key === 'Alt') altUp(); });
        doc.addEventListener('mouseover', (e) => linkHover(e, side, info.frame));
        // A PDF dragged over a pane must not replace the viewer's document
        // (PDF.js opens dropped files by itself): the main window takes the
        // drop, which opens it as a new tab with its real path.
        doc.addEventListener('dragenter', (e) => { if (hasFiles(e)) { e.preventDefault(); showDropZone(); } }, true);
        doc.addEventListener('dragover', (e) => { if (hasFiles(e)) { e.preventDefault(); e.stopPropagation(); showDropZone(); } }, true);
        doc.addEventListener('drop', (e) => { if (hasFiles(e)) { e.preventDefault(); e.stopPropagation(); } }, true);
        if (side === 'translation' && RT.store().night) applyNightToTranslation(true);
    }

    function hasFiles(e) {
        return !!(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'));
    }
    // Full-window drop target in the MAIN document: pywebview gives the dropped
    // file's real path there (bound in web_gui.py) and opens it in a new tab.
    let dropZone = null, dropTimer = null;
    function showDropZone() {
        if (!dropZone) {
            dropZone = document.createElement('div'); dropZone.id = 'rt-dropzone';
            dropZone.innerHTML = '<div class="rt-drop-card"><span class="rt-drop-icon">⇣</span><span class="rt-drop-text"></span></div>';
            const hide = () => { dropZone.style.display = 'none'; };
            dropZone.addEventListener('dragover', (e) => { e.preventDefault(); clearTimeout(dropTimer); dropTimer = setTimeout(hide, 900); });
            dropZone.addEventListener('dragleave', (e) => { if (e.target === dropZone) hide(); });
            dropZone.addEventListener('drop', () => setTimeout(hide, 50));
            document.body.appendChild(dropZone);
        }
        dropZone.querySelector('.rt-drop-text').textContent = RT.t('rd_drop_here');
        dropZone.style.display = 'flex';
        clearTimeout(dropTimer); dropTimer = setTimeout(() => { dropZone.style.display = 'none'; }, 1500);
    }

    function attachPdfViewer() {
        const app = RT.app();
        if (!app || !app.eventBus || !app.pdfDocument || app.__rtReader === app.pdfDocument) return;
        app.__rtReader = app.pdfDocument;
        app.eventBus.on('pagechanging', (evt) => onPageChange(evt.pageNumber));
        app.eventBus.on('pagerendered', (evt) => renderHighlights(evt.pageNumber));
        app.eventBus.on('textlayerrendered', (evt) => renderHighlights(evt.pageNumber));
        if (RT.store().night) applyNightToOriginal(true);
        onDocumentReady();
    }

    setInterval(() => {
        try {
            const pf = RT.pdfFrame(), hf = RT.htmlFrame();
            if (pf && pf.contentDocument && pf.contentDocument.readyState !== 'loading') attach(pf.contentDocument);
            if (hf && hf.contentDocument && hf.contentDocument.body && hf.contentDocument.querySelector('.pf')) attach(hf.contentDocument);
            attachPdfViewer();
        } catch (e) { /* frames reloading */ }
    }, 700);

    // ── Link previews (citations, figures, tables, equations) ───────────────
    let preview = null, hoverTimer = null, previewKey = null;
    const pageCanvasCache = new Map();

    function hidePreview() { clearTimeout(hoverTimer); if (preview && !preview.matches(':hover')) preview.style.display = 'none'; previewKey = null; }

    function linkHover(e, side, frame) {
        const a = e.target.closest && e.target.closest('a');
        if (!a) return;
        let target = null;
        if (side === 'original') {
            const href = a.getAttribute('href') || '';
            if (!href.startsWith('#') || !a.closest('.annotationLayer')) return;
            target = { hash: href.slice(1) };
        } else {
            const detail = a.getAttribute('data-dest-detail');
            if (!detail) return;
            try { const d = JSON.parse(detail); target = { page: d[0] - 1, y: d[1] === 'XYZ' ? d[3] : (d[1] === 'FitH' || d[1] === 'FitBH' ? d[2] : null) }; }
            catch (err) { return; }
        }
        const key = JSON.stringify(target);
        if (key === previewKey) return;
        clearTimeout(hoverTimer);
        const anchor = toMain(frame, a.getBoundingClientRect());
        hoverTimer = setTimeout(() => showPreview(target, anchor).catch((err) => console.warn('[Reader] preview', err)), 280);
        a.addEventListener('mouseleave', () => { clearTimeout(hoverTimer); setTimeout(() => { if (preview && !preview.matches(':hover')) hidePreview(); }, 250); }, { once: true });
        previewKey = key;
    }

    async function resolveTarget(target) {
        const app = RT.app(); if (!app || !app.pdfDocument) return null;
        const pdf = app.pdfDocument;
        if (target.page !== undefined) return { pageIndex: target.page, y: target.y, dest: null };
        let raw = target.hash;
        try { raw = decodeURIComponent(raw); } catch (e) { }
        let dest = null;
        if (raw.startsWith('[')) { try { dest = JSON.parse(raw); } catch (e) { return null; } }
        else if (/^page=\d+/.test(raw)) return { pageIndex: parseInt(raw.slice(5), 10) - 1, y: null, dest: null };
        else dest = await pdf.getDestination(raw);
        if (!Array.isArray(dest)) return null;
        const ref = dest[0];
        const pageIndex = typeof ref === 'object' && ref !== null ? await pdf.getPageIndex(ref) : (Number.isInteger(ref) ? ref : null);
        if (pageIndex === null) return null;
        const kind = dest[1] && dest[1].name;
        const y = kind === 'XYZ' ? dest[3] : (kind === 'FitH' || kind === 'FitBH' ? dest[2] : null);
        return { pageIndex, y, dest };
    }

    async function renderPageCanvas(pageIndex, scale) {
        const key = pageIndex + '@' + scale;
        if (pageCanvasCache.has(key)) return pageCanvasCache.get(key);
        const page = await RT.app().pdfDocument.getPage(pageIndex + 1);
        const viewport = page.getViewport({ scale });
        // Created in the viewer's document: the PDF's embedded fonts are loaded
        // there (rendered from the main window, glyphs come out scrambled).
        const canvas = RT.pdfFrame().contentDocument.createElement('canvas');
        canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
        const entry = { canvas, viewport, page };
        if (pageCanvasCache.size > 12) pageCanvasCache.delete(pageCanvasCache.keys().next().value);
        pageCanvasCache.set(key, entry);
        return entry;
    }

    async function showPreview(target, anchor) {
        const loc = await resolveTarget(target);
        if (!loc) return;
        const scale = 1.6;
        const { canvas, viewport, page } = await renderPageCanvas(loc.pageIndex, scale);
        // Band of the page starting at the destination (or the top of the page)
        const yTopPx = loc.y != null ? Math.max(0, viewport.convertToViewportPoint(0, loc.y)[1] - 8 * scale) : 0;
        // A bibliography entry is short; a figure, table or equation needs room
        const isCitation = /cite|bib|ref/i.test(String(target.hash || ''));
        const bandPx = Math.min(canvas.height - yTopPx, (isCitation ? 70 : 230) * scale);
        const marginPx = Math.round(canvas.width * 0.06);
        const crop = document.createElement('canvas');
        crop.width = canvas.width - 2 * marginPx; crop.height = Math.max(40, bandPx);
        crop.getContext('2d').drawImage(canvas, marginPx, yTopPx, crop.width, crop.height, 0, 0, crop.width, crop.height);

        // Text of the band: arXiv ids / DOIs become actions
        let text = '';
        try {
            const tc = await page.getTextContent();
            const yPdfTop = loc.y != null ? loc.y + 8 : viewport.viewBox[3];
            const yPdfBottom = yPdfTop - 230;
            text = tc.items.filter((it) => it.transform[5] <= yPdfTop && it.transform[5] >= yPdfBottom).map((it) => it.str).join(' ');
        } catch (e) { }
        const arxiv = /arXiv[:\s]*(\d{4}\.\d{4,5})(v\d+)?/i.exec(text) || /arxiv\.org\/abs\/(\d{4}\.\d{4,5})/i.exec(text);
        const doi = /\b(10\.\d{4,9}\/[^\s"<>]+[\w/])/.exec(text);

        if (!preview) {
            preview = document.createElement('div'); preview.id = 'rt-preview'; preview.className = 'rt-pop';
            preview.addEventListener('mouseleave', () => { preview.style.display = 'none'; previewKey = null; });
            document.body.appendChild(preview);
        }
        preview.innerHTML = `<div class="rt-preview-head"><span>p. ${loc.pageIndex + 1}</span><span class="rt-grow"></span>
            ${arxiv ? `<button type="button" data-act="arxiv">${RT.esc(RT.t('rd_open_translate'))} · arXiv ${RT.esc(arxiv[1])}</button>` : ''}
            ${doi ? `<button type="button" data-act="doi">DOI ↗</button>` : ''}
            <button type="button" data-act="go">${RT.esc(RT.t('rd_goto'))} ↓</button></div>`;
        crop.className = 'rt-preview-img';
        preview.appendChild(crop);
        preview.onclick = (e) => {
            const b = e.target.closest('button'); if (!b) return;
            if (b.dataset.act === 'go') goTo(loc);
            if (b.dataset.act === 'arxiv') RT.api().open_pdf_url('https://arxiv.org/abs/' + arxiv[1]);
            if (b.dataset.act === 'doi') RT.api().open_external_link('https://doi.org/' + doi[1]);
            preview.style.display = 'none';
        };
        preview.style.display = 'block';
        const w = Math.min(560, window.innerWidth - 20);
        crop.style.width = w + 'px';
        preview.style.width = w + 'px';
        let top = anchor.bottom + 6;
        if (top + preview.offsetHeight > window.innerHeight - 10) top = Math.max(10, anchor.top - preview.offsetHeight - 6);
        preview.style.left = Math.min(Math.max(10, anchor.left - 40), window.innerWidth - w - 10) + 'px';
        preview.style.top = top + 'px';
    }

    function goTo(loc) {
        const app = RT.app(); if (!app) return;
        if (loc.dest) app.pdfLinkService.goToDestination(loc.dest);
        else if (loc.y != null) app.pdfViewer.scrollPageIntoView({ pageNumber: loc.pageIndex + 1, destArray: [null, { name: 'XYZ' }, null, loc.y + 10, null] });
        else app.page = loc.pageIndex + 1;
    }
    RT.goTo = goTo;

    // Jump to a page and highlight a passage of the original (search, quotes)
    RT.showPassage = function (pageNumber, text) {
        const app = RT.app(); if (!app) return;
        app.page = pageNumber;
        const words = String(text || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim().split(' ').slice(0, 8).join(' ');
        if (words.length < 3) return;
        setTimeout(() => {
            try {
                app.eventBus.dispatch('find', { source: window, type: '', query: words, phraseSearch: true,
                    caseSensitive: false, entireWord: false, highlightAll: false, findPrevious: false, matchDiacritics: false });
            } catch (e) { }
        }, 150);
    };

    // ── Snapshot (area or page) ──────────────────────────────────────────────
    let snapOverlay = null;
    function startSnapshot(side) {
        side = side || 'original';
        const pane = document.getElementById(side === 'original' ? 'left-pane' : 'right-pane');
        if (!pane || pane.offsetParent === null) { if (side === 'original') return startSnapshot('translation'); return; }
        if (snapOverlay) snapOverlay.remove();
        snapOverlay = document.createElement('div'); snapOverlay.className = 'rt-snap-overlay';
        snapOverlay.innerHTML = `<div class="rt-snap-hint">${RT.esc(RT.t('rd_snapshot_hint'))}</div><div class="rt-snap-rect"></div>`;
        pane.appendChild(snapOverlay);
        const rectEl = snapOverlay.querySelector('.rt-snap-rect');
        let start = null;
        const cancel = () => { snapOverlay && snapOverlay.remove(); snapOverlay = null; document.removeEventListener('keydown', onKey, true); };
        const onKey = (e) => { if (e.key === 'Escape') cancel(); };
        document.addEventListener('keydown', onKey, true);
        snapOverlay.addEventListener('mousedown', (e) => { start = { x: e.clientX, y: e.clientY }; });
        snapOverlay.addEventListener('mousemove', (e) => {
            if (!start) return;
            const pr = snapOverlay.getBoundingClientRect();
            const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
            Object.assign(rectEl.style, { display: 'block', left: (x - pr.left) + 'px', top: (y - pr.top) + 'px',
                width: Math.abs(e.clientX - start.x) + 'px', height: Math.abs(e.clientY - start.y) + 'px' });
        });
        snapOverlay.addEventListener('mouseup', (e) => {
            if (!start) return;
            const area = { left: Math.min(start.x, e.clientX), top: Math.min(start.y, e.clientY),
                           right: Math.max(start.x, e.clientX), bottom: Math.max(start.y, e.clientY) };
            cancel();
            if (area.right - area.left < 8 || area.bottom - area.top < 8) return;
            (side === 'original' ? captureOriginal(area) : captureTranslation(area)).catch((err) => console.error(err));
        });
    }
    RT.startSnapshot = startSnapshot;

    // Original: crop straight from the PDF.js page canvases
    async function captureOriginal(area) {
        const frame = RT.pdfFrame(), fr = frame.getBoundingClientRect(), doc = frame.contentDocument;
        const canvases = Array.from(doc.querySelectorAll('.page canvas'));
        let ratio = 1;
        canvases.forEach((c) => { const r = c.getBoundingClientRect(); if (r.width) ratio = Math.max(ratio, c.width / r.width); });
        const out = document.createElement('canvas');
        out.width = Math.round((area.right - area.left) * ratio); out.height = Math.round((area.bottom - area.top) * ratio);
        const ctx = out.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, out.width, out.height);
        canvases.forEach((c) => {
            const r = c.getBoundingClientRect(), k = c.width / r.width;
            const L = Math.max(area.left, fr.left + r.left), T = Math.max(area.top, fr.top + r.top);
            const R = Math.min(area.right, fr.left + r.right), B = Math.min(area.bottom, fr.top + r.bottom);
            if (R <= L || B <= T) return;
            ctx.drawImage(c, (L - fr.left - r.left) * k, (T - fr.top - r.top) * k, (R - L) * k, (B - T) * k,
                (L - area.left) * ratio, (T - area.top) * ratio, (R - L) * ratio, (B - T) * ratio);
        });
        await RT.copyImage(out, 'snapshot.png');
    }

    // Translation: the page is rendered by a headless browser, then cropped
    async function captureTranslation(area) {
        const frame = RT.htmlFrame(), fr = frame.getBoundingClientRect(), doc = frame.contentDocument;
        const cx = (area.left + area.right) / 2 - fr.left, cy = (area.top + area.bottom) / 2 - fr.top;
        const pages = Array.from(doc.querySelectorAll('.pf'));
        const idx = pages.findIndex((p) => { const r = p.getBoundingClientRect(); return cy >= r.top && cy <= r.bottom && cx >= r.left && cx <= r.right; });
        if (idx < 0) return;
        const pr = pages[idx].getBoundingClientRect();
        const png = await translatedPagePng(idx);
        if (!png) return;
        const img = new Image(); img.src = 'data:image/png;base64,' + png; await img.decode();
        const k = img.width / pr.width;
        const out = document.createElement('canvas');
        const L = Math.max(area.left - fr.left, pr.left), T = Math.max(area.top - fr.top, pr.top);
        const R = Math.min(area.right - fr.left, pr.right), B = Math.min(area.bottom - fr.top, pr.bottom);
        out.width = Math.round((R - L) * k); out.height = Math.round((B - T) * k);
        out.getContext('2d').drawImage(img, (L - pr.left) * k, (T - pr.top) * k, out.width, out.height, 0, 0, out.width, out.height);
        await RT.copyImage(out, 'snapshot.png');
    }

    function translatedPagePng(pageIndex) {
        return new Promise((resolve) => {
            RT.toast(RT.t('rd_working'), 'info', 2000);
            RT.request((id) => RT.api().snapshot_translated_page(pageIndex, id), null, (res) => {
                if (!res.ok) { RT.toast(RT.t('rd_error', { error: res.error || '?' }), 'error'); resolve(null); }
                else resolve(res.png);
            });
        });
    }

    async function copyOriginalPage(pageNumber) {
        pageNumber = pageNumber || RT.store().currentPage;
        const { canvas } = await renderPageCanvas(pageNumber - 1, 2.5);
        await RT.copyImage(canvas, `page-${pageNumber}.png`);
    }
    async function copyTranslatedPage(pageNumber) {
        pageNumber = pageNumber || RT.store().currentPage;
        const png = await translatedPagePng(pageNumber - 1);
        if (png) await RT.copyImage('data:image/png;base64,' + png, `page-${pageNumber}-translated.png`);
    }
    RT.copyOriginalPage = copyOriginalPage;
    RT.copyTranslatedPage = copyTranslatedPage;

    // ── Night reading (figures are not inverted) ────────────────────────────
    const NIGHT = { background: '#1e1f22', foreground: '#d9d9de' };
    function applyNightToOriginal(on) {
        const app = RT.app(); if (!app || !app.pdfViewer) return;
        const colors = on ? NIGHT : null;
        try {
            app.pdfViewer.pageColors = colors;
            (app.pdfViewer._pages || []).forEach((v) => { v.pageColors = colors; v.reset(); });
            app.pdfViewer.update();
            const doc = RT.pdfFrame().contentDocument;
            doc.documentElement.classList.toggle('rt-night', on);
            let st = doc.getElementById('rt-night-style');
            if (!st) { st = doc.createElement('style'); st.id = 'rt-night-style'; doc.head.appendChild(st); }
            st.textContent = on ? '#viewerContainer{background:#121214!important}.pdfViewer .page{border-color:#121214!important;background:#1e1f22!important}' : '';
        } catch (e) { console.warn('[Reader] night (original)', e); }
    }
    function applyNightToTranslation(on) {
        try {
            const doc = RT.htmlFrame().contentDocument; if (!doc || !doc.head) return;
            let st = doc.getElementById('rt-night-style');
            if (!st) { st = doc.createElement('style'); st.id = 'rt-night-style'; doc.head.appendChild(st); }
            // pdf2htmlEX draws the paper, the figures and the lines in ONE page
            // image: inverting it would invert the figures too. The page is
            // dimmed instead (no glare, figures and colors intact) on a dark desk.
            st.textContent = on ? `html,body,#page-container{background:#121214!important}
                .pf{filter:brightness(.74) contrast(1.08);box-shadow:none!important}` : '';
        } catch (e) { }
    }
    RT.setNight = function (on) {
        RT.store().night = on; setPref('night', on);
        applyNightToOriginal(on); applyNightToTranslation(on);
    };

    // ── Continuous translation, resume position ─────────────────────────────
    let pageTimer = null, saveTimer = null, pendingSave = null;
    RT.flushPosition = () => { clearTimeout(saveTimer); if (pendingSave) pendingSave(); };
    function onPageChange(pageNumber) {
        const store = RT.store(); store.currentPage = pageNumber;
        clearTimeout(saveTimer);
        const path = store.activePath;
        pendingSave = () => { pendingSave = null; if (RT.api()) RT.api().save_reading_position(pageNumber, null, path); };
        saveTimer = setTimeout(() => pendingSave && pendingSave(), 1200);
        if (store.continuous) {
            clearTimeout(pageTimer);
            pageTimer = setTimeout(() => translatePages([pageNumber - 1, pageNumber], false), 900);
        }
    }
    async function translatePages(pages, explicit) {
        const api = RT.api(); if (!api) return;
        if (Alpine.store('trans').running) { if (explicit) RT.toast(RT.t('status_trans_is_running') || '…', 'warning'); return; }
        const res = await api.auto_translate_pages(pages);
        if (res && res.status === 'started') Alpine.store('trans').running = true;
    }
    RT.translatePages = translatePages;
    RT.setContinuous = function (on) {
        RT.store().continuous = on; setPref('continuous', on);
        RT.toast(RT.t(on ? 'rd_continuous_on' : 'rd_continuous_off'), 'info', 4000);
        if (on) translatePages([RT.store().currentPage - 1, RT.store().currentPage], false);
    };
    window.addEventListener('trigger-translation-finished', () => {
        if (RT.store() && RT.store().continuous) setTimeout(() => translatePages([RT.store().currentPage - 1, RT.store().currentPage], false), 600);
    });

    async function onDocumentReady() {
        const api = RT.api(); if (!api) return;
        try {
            RT.store().highlights = (await api.get_highlights()) || [];
            const pos = await api.get_reading_position();
            const app = RT.app();
            if (pos && pos.page > 1 && app && app.page === 1 && pos.page <= app.pagesCount) {
                setTimeout(() => { app.page = pos.page; RT.toast(RT.t('rd_resume', { page: pos.page }), 'info', 2500); }, 300);
            }
        } catch (e) { console.warn('[Reader] restore', e); }
        for (let p = 1; p <= (RT.app().pagesCount || 0); p++) renderHighlights(p);
        window.dispatchEvent(new CustomEvent('reader-document-ready'));
    }

    // ── Highlights and notes (original pane) ────────────────────────────────
    const HL_COLORS = ['#ffe066', '#9be7a1', '#9ccfff', '#ffb3c7'];
    function addHighlight(sel) {
        if (sel.side !== 'original' || !sel.pageEl) return;
        const pr = sel.pageEl.getBoundingClientRect();
        const rects = Array.from(sel.range.getClientRects()).filter((r) => r.width > 1 && r.height > 1)
            .map((r) => [(r.left - pr.left) / pr.width, (r.top - pr.top) / pr.height, r.width / pr.width, r.height / pr.height]);
        if (!rects.length) return;
        const store = RT.store();
        const item = { id: 'h' + Date.now().toString(36), page: sel.pageNumber, rects, text: sel.text.replace(/\s+/g, ' ').trim(),
                       color: HL_COLORS[0], note: '', created: new Date().toISOString() };
        store.highlights = store.highlights.concat([item]);
        RT.saveHighlights();
        try { sel.frame.contentDocument.getSelection().removeAllRanges(); } catch (e) { }
        renderHighlights(sel.pageNumber);
        if (!store.panelOpen || store.panelTab !== 'notes') store.togglePanel('notes');
    }
    RT.saveHighlights = () => RT.api() && RT.api().save_highlights(JSON.parse(JSON.stringify(RT.store().highlights)));
    function renderHighlights(pageNumber) {
        try {
            const doc = RT.pdfFrame().contentDocument;
            const pageEl = doc.querySelector(`.page[data-page-number="${pageNumber}"]`); if (!pageEl) return;
            pageEl.querySelectorAll('.rt-hl').forEach((n) => n.remove());
            RT.store().highlights.filter((h) => h.page === pageNumber).forEach((h) => {
                h.rects.forEach(([x, y, w, hh]) => {
                    const d = doc.createElement('div'); d.className = 'rt-hl'; d.dataset.id = h.id;
                    Object.assign(d.style, { position: 'absolute', left: (x * 100) + '%', top: (y * 100) + '%', width: (w * 100) + '%',
                        height: (hh * 100) + '%', background: h.color, opacity: '0.38', mixBlendMode: 'multiply',
                        pointerEvents: 'none', zIndex: '1', borderRadius: '2px' });
                    pageEl.appendChild(d);
                });
            });
        } catch (e) { }
    }
    RT.renderHighlights = renderHighlights;
    RT.HL_COLORS = HL_COLORS;

    // ── Hold Alt: original in the translation-only view ─────────────────────
    let altHeld = false, altUsed = false;
    window.addEventListener('trigger-layout-change', (e) => {
        if (!altHeld && e.detail && e.detail.mode) RT.store().layout = e.detail.mode;
    });
    function altDown() {
        if (altHeld || RT.store().layout !== 'trans_only') return;
        altHeld = true; altUsed = false;
        window.dispatchEvent(new CustomEvent('trigger-layout-change', { detail: { mode: 'pdf_only' } }));
    }
    function altUp() {
        if (!altHeld) return;
        altHeld = false;
        window.dispatchEvent(new CustomEvent('trigger-layout-change', { detail: { mode: 'trans_only' } }));
    }

    // ── Keyboard shortcuts ───────────────────────────────────────────────────
    function shortcutFor(e) {
        const k = (e.key || '').toLowerCase();
        const ctrl = e.ctrlKey || e.metaKey;
        if (ctrl && !e.shiftKey && k === 'k') return () => RT.palette.open();
        if (!RT.docOpen()) return null;
        if (ctrl && !e.shiftKey && k === 't') return () => runOnSelection('translate');
        if (ctrl && !e.shiftKey && k === 'e') return () => runOnSelection('explain');
        if (ctrl && !e.shiftKey && k === 'h') return () => runOnSelection('highlight');
        if (ctrl && !e.shiftKey && k === 'b') return () => RT.store().togglePanel();
        if (ctrl && !e.shiftKey && k === 'f') return () => { RT.store().panelOpen = false; RT.store().togglePanel('search'); setTimeout(() => window.dispatchEvent(new CustomEvent('reader-focus-search')), 80); };
        if (ctrl && !e.shiftKey && k === 'j') return () => { RT.store().panelOpen = false; RT.store().togglePanel('ask'); setTimeout(() => window.dispatchEvent(new CustomEvent('reader-focus-ask')), 80); };
        if (ctrl && e.shiftKey && k === 's') return () => startSnapshot('original');
        if (ctrl && e.shiftKey && k === 'n') return () => RT.setNight(!RT.store().night);
        return null;
    }
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { hideToolbar(); hideMenu(); closeBubble(); if (preview) preview.style.display = 'none'; }
        if (e.key === 'Alt' && !e.ctrlKey && !e.shiftKey) { altDown(); return; }
        if (altHeld) altUsed = true;
        const fn = shortcutFor(e);
        if (fn) { if (e.cancelable) e.preventDefault(); fn(); }
    });
    window.addEventListener('keyup', (e) => { if (e.key === 'Alt') altUp(); });
    window.addEventListener('blur', altUp);
    document.addEventListener('mousedown', (e) => {
        if (menu && !e.target.closest('#rt-ctxmenu')) hideMenu();
        if (toolbar && !e.target.closest('#rt-seltool')) hideToolbar();
    });

    // ── Tabs (open documents of the session) ─────────────────────────────────
    window.addEventListener('document-ready', (e) => {
        const path = e.detail && e.detail.pdfPath; if (!path) return;
        const store = Alpine.store('reader');
        const name = path.split(/[\\/]/).pop();
        if (!store.tabs.some((t) => t.path === path)) store.tabs = store.tabs.concat([{ path, name }]);
        store.activePath = path;
        store.currentPage = 1;
    });
    window.addEventListener('trigger-close-document', () => { RT.flushPosition(); const s = Alpine.store('reader'); s.activePath = null; });
    window.addEventListener('trigger-file-picker', () => RT.flushPosition());
    RT.switchTab = function (path) {
        const store = RT.store();
        if (path === store.activePath) return;
        if (Alpine.store('trans').running) { RT.toast(RT.t('rd_busy_switch'), 'warning', 4000); return; }
        RT.flushPosition();
        RT.api().extract_pdf(path);
    };
    RT.closeTab = function (path) {
        const store = RT.store();
        if (path === store.activePath && Alpine.store('trans').running) { RT.toast(RT.t('rd_busy_switch'), 'warning', 4000); return; }
        const i = store.tabs.findIndex((t) => t.path === path);
        store.tabs = store.tabs.filter((t) => t.path !== path);
        if (path === store.activePath) {
            const next = store.tabs[Math.min(i, store.tabs.length - 1)];
            if (next) RT.api().extract_pdf(next.path);
            else window.dispatchEvent(new CustomEvent('trigger-close-document'));
        }
    };

    // ── Command palette ──────────────────────────────────────────────────────
    const commands = () => {
        const s = RT.store(), doc = RT.docOpen(), t = RT.t;
        const list = [
            { id: 'open', label: t('item_open'), sc: '', run: () => window.dispatchEvent(new CustomEvent('trigger-file-picker')) },
            { id: 'open-link', label: t('rd_open_link'), run: () => { const u = window.prompt(t('rd_link_prompt')); if (u) RT.api().open_pdf_url(u); } },
        ];
        if (doc) list.push(
            { id: 'translate-all', label: t('item_start_trans'), run: () => window.dispatchEvent(new CustomEvent('trigger-toggle-translation')) },
            { id: 'translate-page', label: t('rd_translate_page') + ` (${s.currentPage})`, run: () => translatePages([s.currentPage - 1], true) },
            { id: 'continuous', label: t('rd_continuous') + (s.continuous ? ' ✓' : ''), run: () => RT.setContinuous(!s.continuous) },
            { id: 'translate-sel', label: t('rd_translate') + ' · Ctrl+T', sc: 'Ctrl+T', run: () => runOnSelection('translate') },
            { id: 'explain-sel', label: t('rd_explain') + ' · Ctrl+E', sc: 'Ctrl+E', run: () => runOnSelection('explain') },
            { id: 'panel', label: t('rd_panel'), sc: 'Ctrl+B', run: () => s.togglePanel() },
            { id: 'toc', label: t('rd_tab_toc'), run: () => s.togglePanel('toc') },
            { id: 'search', label: t('rd_search_doc'), sc: 'Ctrl+F', run: () => { s.panelOpen = false; s.togglePanel('search'); setTimeout(() => window.dispatchEvent(new CustomEvent('reader-focus-search')), 80); } },
            { id: 'ask', label: t('rd_ask_doc'), sc: 'Ctrl+J', run: () => { s.panelOpen = false; s.togglePanel('ask'); setTimeout(() => window.dispatchEvent(new CustomEvent('reader-focus-ask')), 80); } },
            { id: 'notes', label: t('rd_tab_notes'), run: () => s.togglePanel('notes') },
            { id: 'glossary', label: t('rd_tab_glossary'), run: () => s.togglePanel('glossary') },
            { id: 'snapshot', label: t('rd_snapshot'), sc: 'Ctrl+Shift+S', run: () => startSnapshot('original') },
            { id: 'page-image', label: t('rd_page_image'), run: () => copyOriginalPage() },
            { id: 'tpage-image', label: t('rd_trans_page_image'), run: () => copyTranslatedPage() },
            { id: 'night', label: t('rd_night') + (s.night ? ' ✓' : ''), sc: 'Ctrl+Shift+N', run: () => RT.setNight(!s.night) },
            { id: 'export', label: t('item_export'), run: () => window.pywebview.api.export_translated_pdf() },
            { id: 'sbs', label: t('rd_sbs'), run: () => RT.api().export_side_by_side() },
            { id: 'notes-export', label: t('rd_export_notes'), run: () => window.dispatchEvent(new CustomEvent('reader-export-notes')) },
            { id: 'layout-both', label: t('item_layout_both'), run: () => window.dispatchEvent(new CustomEvent('trigger-layout-change', { detail: { mode: 'both' } })) },
            { id: 'layout-trans', label: t('item_layout_trans'), run: () => window.dispatchEvent(new CustomEvent('trigger-layout-change', { detail: { mode: 'trans_only' } })) },
            { id: 'layout-pdf', label: t('item_layout_pdf'), run: () => window.dispatchEvent(new CustomEvent('trigger-layout-change', { detail: { mode: 'pdf_only' } })) },
        );
        list.push(
            { id: 'prefs', label: t('prefs_menu_item'), run: () => window.dispatchEvent(new CustomEvent('open-preferences', { detail: {} })) },
            { id: 'shortcuts', label: t('rd_shortcuts'), run: () => RT.toast(t('rd_shortcut_list'), 'info', 12000) },
        );
        return list;
    };
    RT.commands = commands;

    RT.palette = (function () {
        let el = null, items = [], active = 0;
        function render(q) {
            const fold = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
            const words = fold(q || '').split(/\s+/).filter(Boolean);
            items = commands().filter((c) => words.every((w) => fold(c.label).includes(w)));
            active = Math.min(active, Math.max(0, items.length - 1));
            el.querySelector('.rt-pal-list').innerHTML = items.map((c, i) =>
                `<div class="rt-pal-item${i === active ? ' active' : ''}" data-i="${i}"><span>${RT.esc(c.label)}</span>` +
                `<span class="rt-sc">${RT.esc(c.sc || '')}</span></div>`).join('');
        }
        function close() { if (el) el.style.display = 'none'; }
        function run(i) { const c = items[i]; close(); if (c) setTimeout(c.run, 10); }
        function open() {
            if (!el) {
                el = document.createElement('div'); el.id = 'rt-palette';
                el.innerHTML = `<div class="rt-pal-box rt-pop"><input class="rt-pal-input" type="text" autocomplete="off"><div class="rt-pal-list"></div></div>`;
                el.addEventListener('mousedown', (e) => { if (e.target === el) close(); });
                const input = el.querySelector('input');
                input.addEventListener('input', () => { active = 0; render(input.value); });
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); render(input.value); e.preventDefault(); }
                    else if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); render(input.value); e.preventDefault(); }
                    else if (e.key === 'Enter') { run(active); e.preventDefault(); }
                    else if (e.key === 'Escape') { close(); e.preventDefault(); }
                    e.stopPropagation();
                });
                el.querySelector('.rt-pal-list').addEventListener('click', (e) => { const it = e.target.closest('[data-i]'); if (it) run(+it.dataset.i); });
                document.body.appendChild(el);
            }
            const input = el.querySelector('input');
            input.placeholder = RT.t('rd_palette_ph');
            input.value = ''; active = 0; render('');
            el.style.display = 'flex';
            setTimeout(() => input.focus(), 10);
        }
        return { open, close };
    })();
})();
