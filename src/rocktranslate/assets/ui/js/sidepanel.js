/**
 * RockTranslate — Reader side panel (Alpine component)
 * Path: src/rocktranslate/assets/ui/js/sidepanel.js
 *
 * Tabs: Contents (PDF bookmarks, or headings detected on the pages when the
 * PDF has none, each section summarizable), bilingual Search, Ask the paper
 * (answers with verbatim quotes that open the exact passage), Notes
 * (highlights, exported as Markdown) and the paper Glossary (one translation
 * per term, applied to the document's translations).
 *
 * Author: RockTranslate Contributors
 * License: MIT License
 */

// ── Page text as lines (PDF.js text content), cached per document ─────────
const rtPageLines = new Map();

async function rtGetPageLines(app, pageNumber) {
    const key = app.pdfDocument.fingerprints ? app.pdfDocument.fingerprints[0] + ':' + pageNumber : String(pageNumber);
    if (rtPageLines.has(key)) return rtPageLines.get(key);
    const page = await app.pdfDocument.getPage(pageNumber);
    const tc = await page.getTextContent();
    const lines = [];
    tc.items.forEach((it) => {
        if (!it.str || !it.str.trim()) return;
        // Rotated text (arXiv stamps, axis labels) is never part of a heading
        if (Math.abs(it.transform[1]) > 0.01 || Math.abs(it.transform[2]) > 0.01) return;
        const x = it.transform[4], y = it.transform[5], h = Math.abs(it.transform[3]) || Math.abs(it.height) || 0;
        // Same baseline and close horizontally: same line (columns stay apart)
        const line = lines.find((l) => Math.abs(l.y - y) < Math.max(1.5, h * 0.3) && x >= l.x - 2 && x - l.end < Math.max(12, 3 * h));
        if (line) {
            line.text += (x - line.end > h * 0.15 && !line.text.endsWith(' ') ? ' ' : '') + it.str;
            line.end = x + (it.width || 0); line.h = Math.max(line.h, h);
            line.chars[it.fontName] = (line.chars[it.fontName] || 0) + it.str.length;
        } else {
            lines.push({ page: pageNumber, x, y, end: x + (it.width || 0), h, text: it.str, chars: { [it.fontName]: it.str.length } });
        }
    });
    lines.forEach((l) => {
        l.text = l.text.replace(/\s+/g, ' ').trim();
        l.font = Object.keys(l.chars).sort((a, b) => l.chars[b] - l.chars[a])[0];
    });
    lines.sort((a, b) => (b.y - a.y) || (a.x - b.x));
    rtPageLines.set(key, lines);
    return lines;
}

const RT_KNOWN_HEADINGS = /^(?:(?:\d+|[IVX]+)\.?\s*)?(abstract|introduction|related work|background|methods?|methodology|materials and methods|results?|discussion|conclusions?|references|bibliography|acknowledge?ments?|appendix|appendices|résumé|introduction|conclusion|références|bibliographie|remerciements|annexe)s?\b\.?$/i;
// "3", "3.2.1", "2.a.1", "IV." and "A." (letters need their dot: "P E(pos)" is math)
const RT_NUMBERED = /^((?:\d+(?:\.(?:\d+|[a-z]))*\.?)|(?:[IVX]{1,5}|[A-Z])\.)\s+\S/;

async function rtDetectHeadings(app) {
    const n = app.pdfDocument.numPages;
    const all = [];
    for (let p = 1; p <= n; p++) all.push(...await rtGetPageLines(app, p));
    // Body text = the most frequent line height and font (weighted by characters)
    const hCount = {}, fCount = {};
    all.forEach((l) => {
        const hk = Math.round(l.h * 2) / 2;
        hCount[hk] = (hCount[hk] || 0) + l.text.length;
        fCount[l.font] = (fCount[l.font] || 0) + l.text.length;
    });
    const bodyH = +Object.keys(hCount).sort((a, b) => hCount[b] - hCount[a])[0] || 10;
    const bodyFont = Object.keys(fCount).sort((a, b) => fCount[b] - fCount[a])[0];
    // Running headers repeat on many pages: never headings
    const seen = {};
    all.forEach((l) => { const k = l.text.replace(/\s+/g, '').toLowerCase(); seen[k] = (seen[k] || new Set()).add(l.page); });
    const out = [];
    all.forEach((l) => {
        const t = l.text, words = t.split(' ').length;
        if (t.length < 3 || t.length > 110 || words > 16) return;
        if (/[=<>≤≥∑∫]|\(\w+,\w+\)/.test(t)) return;           // equations
        if (seen[t.replace(/\s+/g, '').toLowerCase()].size >= 3) return;
        const otherFont = l.font !== bodyFont, bigger = l.h >= bodyH * 1.08;
        const compact = t.replace(/\s+/g, '');
        const m = RT_NUMBERED.exec(t);
        let depth = null;
        if (RT_KNOWN_HEADINGS.test(t) || RT_KNOWN_HEADINGS.test(compact)) {
            if (otherFont || bigger) depth = m ? m[1].replace(/\.$/, '').split('.').length - 1 : 0;
        } else if (m && (otherFont || bigger) && !/[,;]$/.test(t) && /[A-Za-zÀ-ÿ]{3}/.test(t)) {
            if (/^\d/.test(m[1]) && +m[1].split('.')[0] > 30) return;      // a number, not a section
            depth = /^\d/.test(m[1]) ? m[1].replace(/\.$/, '').split('.').length - 1 : 0;
            if (!/^\d/.test(m[1]) && !/^[IVX]+\.$|^[A-Z]\.$/.test(m[1])) return;
        }
        if (depth !== null) out.push({ title: t, depth: Math.min(depth, 3), page: l.page, y: l.y + l.h, dest: null });
    });
    // Paper title: biggest line of page 1
    const first = all.filter((l) => l.page === 1).sort((a, b) => b.h - a.h)[0];
    if (first && first.h >= bodyH * 1.4 && !out.some((o) => o.page === 1 && o.title === first.text)) {
        out.unshift({ title: first.text, depth: 0, page: 1, y: first.y + first.h, dest: null, isTitle: true });
    }
    return out.slice(0, 250);
}

async function rtOutline(app) {
    const outline = await app.pdfDocument.getOutline();
    if (!outline || !outline.length) return null;
    const out = [];
    const walk = (items, depth) => items.forEach((it) => {
        out.push({ title: it.title, depth: Math.min(depth, 3), dest: it.dest, page: null, y: null });
        if (it.items && it.items.length) walk(it.items, depth + 1);
    });
    walk(outline, 0);
    // Page and position of each entry (for "go to" and section text)
    for (const it of out) {
        try {
            let dest = it.dest;
            if (typeof dest === 'string') dest = await app.pdfDocument.getDestination(dest);
            if (!Array.isArray(dest)) continue;
            const ref = dest[0];
            it.page = (typeof ref === 'object' && ref !== null ? await app.pdfDocument.getPageIndex(ref) : ref) + 1;
            const kind = dest[1] && dest[1].name;
            it.y = kind === 'XYZ' ? dest[3] : (kind === 'FitH' || kind === 'FitBH' ? dest[2] : null);
            it.dest = dest;
        } catch (e) { }
    }
    return out.slice(0, 400);
}

function sidePanel() {
    return {
        toc: [], tocAuto: false, tocLoading: false, summaries: {}, collapsed: {},
        q: '', results: [], searching: false, searched: false,
        question: '', thread: [], asking: false,
        glossary: [], glossUse: true, glossBusy: false, glossDirty: false,

        init() {
            const load = () => this.load();
            window.addEventListener('reader-document-ready', load);
            window.addEventListener('reader-focus-search', () => this.$nextTick(() => this.$refs.search && this.$refs.search.focus()));
            window.addEventListener('reader-focus-ask', () => this.$nextTick(() => this.$refs.ask && this.$refs.ask.focus()));
            window.addEventListener('reader-export-notes', () => this.exportNotes());
            const app = RT.app();
            if (app && app.pdfDocument) load();
        },

        t(key, vars) { return Alpine.store('i18n').translate(key, vars || {}); },

        async load() {
            this.toc = []; this.summaries = {}; this.collapsed = {}; this.results = []; this.thread = []; this.searched = false;
            this.loadGlossary();
            this.tocLoading = true;
            try {
                const app = RT.app();
                const outline = await rtOutline(app);
                this.tocAuto = !outline;
                this.toc = outline || await rtDetectHeadings(app);
            } catch (e) { console.warn('[Panel] contents', e); }
            this.tocLoading = false;
        },

        // ── Contents ──
        // (the list can be replaced while the template still renders old rows)
        hasChildren(i) { const it = this.toc[i], next = this.toc[i + 1]; return !!it && !!next && next.depth > it.depth; },
        // Hidden when one of its ancestors is collapsed
        isVisible(i) {
            if (!this.toc[i]) return false;
            let depth = this.toc[i].depth;
            for (let k = i - 1; k >= 0 && depth > 0; k--) {
                if (this.toc[k].depth < depth) {
                    if (this.collapsed[k]) return false;
                    depth = this.toc[k].depth;
                }
            }
            return true;
        },
        toggleSection(i) { this.collapsed = { ...this.collapsed, [i]: !this.collapsed[i] }; },
        collapseAll(on) {
            const next = {};
            if (on) this.toc.forEach((_, i) => { if (this.hasChildren(i)) next[i] = true; });
            this.collapsed = next;
        },
        toggleSummary(i) { const s = this.summaries[i]; if (s) this.summaries = { ...this.summaries, [i]: { ...s, open: !s.open } }; },
        closeSummary(i) { const next = { ...this.summaries }; delete next[i]; this.summaries = next; },

        goToc(item) {
            if (item.dest) { RT.app().pdfLinkService.goToDestination(item.dest); return; }
            RT.goTo({ pageIndex: item.page - 1, y: item.y, dest: null });
        },

        async sectionText(i) {
            const app = RT.app(), start = this.toc[i];
            const next = this.toc.slice(i + 1).find((o) => o.depth <= start.depth && o.page) || null;
            const lastPage = next ? next.page : app.pdfDocument.numPages;
            const parts = [];
            for (let p = start.page; p <= lastPage && parts.join(' ').length < 60000; p++) {
                (await rtGetPageLines(app, p)).forEach((l) => {
                    const afterStart = p > start.page || start.y == null || l.y <= start.y + 1;
                    const beforeNext = !next || p < next.page || next.y == null || l.y > next.y + 1;
                    if (afterStart && beforeNext) parts.push(l.text);
                });
            }
            return parts.join('\n');
        },

        async summarize(i) {
            const item = this.toc[i];
            if (!item.page) return;
            if (this.summaries[i] && !this.summaries[i].loading) { this.toggleSummary(i); return; }
            this.summaries = { ...this.summaries, [i]: { text: '', loading: true, open: true } };
            const text = await this.sectionText(i);
            RT.assist('summarize', text, (piece) => {
                const s = this.summaries[i]; this.summaries = { ...this.summaries, [i]: { ...s, text: s.text + piece } };
            }, (res) => {
                const s = this.summaries[i] || { text: '' };
                this.summaries = { ...this.summaries, [i]: { text: s.text || res.text || (res.ok ? '' : this.t('rd_error', { error: res.error })), loading: false, open: s.open !== false } };
            }, { title: item.title });
        },

        // ── Bilingual search ──
        async search() {
            const q = this.q.trim();
            if (q.length < 2) { this.results = []; this.searched = false; return; }
            this.searching = true;
            try { this.results = (await RT.api().search_document(q)) || []; } catch (e) { this.results = []; }
            this.searching = false; this.searched = true;
        },
        openResult(r) { RT.showPassage(r.page, r.side === 'original' ? this.q : r.original); },

        // ── Ask the paper ──
        ask() {
            const q = this.question.trim();
            if (!q || this.asking) return;
            const entry = { q, a: '', quotes: [], loading: true, cost: 0 };
            this.thread = this.thread.concat([entry]);
            const index = this.thread.length - 1;
            this.question = ''; this.asking = true;
            RT.assist('ask', q, null, (res) => {
                const done = { ...this.thread[index], loading: false,
                    a: res.ok ? res.text : this.t('rd_error', { error: res.error || '?' }), quotes: res.quotes || [], cost: res.cost || 0 };
                this.thread = this.thread.map((e, k) => (k === index ? done : e));
                this.asking = false;
                this.$nextTick(() => { const box = this.$refs.thread; if (box) box.scrollTop = box.scrollHeight; });
            });
        },
        openQuote(q) { RT.showPassage(q.page, q.quote); },

        // ── Notes ──
        get notes() { return (Alpine.store('reader').highlights || []).slice().sort((a, b) => a.page - b.page); },
        updateNote(h, fields) {
            const store = Alpine.store('reader');
            store.highlights = store.highlights.map((x) => (x.id === h.id ? { ...x, ...fields } : x));
            RT.saveHighlights(); RT.renderHighlights(h.page);
        },
        deleteNote(h) {
            const store = Alpine.store('reader');
            store.highlights = store.highlights.filter((x) => x.id !== h.id);
            RT.saveHighlights(); RT.renderHighlights(h.page);
        },
        async exportNotes() {
            const c = (await RT.api().get_doc_citation()) || {};
            const lines = [`# ${c.title || 'Notes'}`, ''];
            if (c.short || c.doi) lines.push(`*${[c.short, c.doi ? 'https://doi.org/' + c.doi : ''].filter(Boolean).join(' · ')}*`, '');
            let page = null;
            this.notes.forEach((h) => {
                if (h.page !== page) { page = h.page; lines.push(`## Page ${page}`, ''); }
                lines.push(`> ${h.text}`, '');
                if (h.note) lines.push(h.note, '');
            });
            const name = ((c.title || 'notes').replace(/[^\w\- ]+/g, '').trim().slice(0, 60) || 'notes') + '.md';
            const res = await RT.api().save_text_file(lines.join('\n'), name);
            if (res && res.status === 'success') RT.toast(res.path, 'success', 4000);
        },

        // ── Glossary ──
        async loadGlossary() {
            try {
                const g = await RT.api().get_doc_glossary();
                this.glossary = g.items || []; this.glossUse = g.use !== false; this.glossDirty = false;
            } catch (e) { this.glossary = []; }
        },
        generateGlossary() {
            if (this.glossBusy) return;
            this.glossBusy = true;
            RT.request((id) => RT.api().generate_doc_glossary(id), null, (res) => {
                this.glossBusy = false;
                if (res.ok) { this.glossary = res.items || []; this.glossDirty = false; RT.toast(this.t('rd_gloss_saved'), 'success', 2500); }
                else if (res.error !== 'no_key') RT.toast(this.t('rd_error', { error: res.error || '?' }), 'error');
            });
        },
        addTerm() { this.glossary = this.glossary.concat([{ term: '', translation: '', note: '' }]); this.glossDirty = true; },
        removeTerm(i) { this.glossary = this.glossary.filter((_, k) => k !== i); this.glossDirty = true; },
        async saveGlossary() {
            await RT.api().save_doc_glossary(JSON.parse(JSON.stringify(this.glossary)), this.glossUse);
            this.glossDirty = false;
            RT.toast(this.t('rd_gloss_saved'), 'success', 2000);
        },
    };
}
