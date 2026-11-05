/**
 * RockTranslate — Progress Panel Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/progress.js
 * 
 * Manages reactive translation progress and calculates relative speeds and range ETAs.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.1
 */

function progressController() {
    return {
        visible: true,

        totalPages: 0,
        donePages: 0,
        totalSegments: 0,
        doneSegments: 0,
        batchesDone: 0,
        batchesTotal: 0,

        // Range index map array
        targetPages: null,

        startTime: null,
        speed: 0,
        eta: '',

        // Live run statistics pushed by the backend ('update-usage')
        usage: null,
        elapsedTick: 0,
        _tickTimer: null,

        init() {
            window.addEventListener('trigger-toggle-progress', (e) => {
                this.visible = e.detail.visible;
            });

            window.addEventListener('document-ready', (e) => {
                this.initializeBounds(e.detail.totalPages, e.detail.totalSegments);
            });

            window.addEventListener('update-progress-page', (e) => {
                if (e.detail && e.detail.page) {
                    this.setPage(e.detail.page);
                }
            });

            window.addEventListener('update-progress-segment', () => {
                this.incrementSegment();
            });

            window.addEventListener('update-progress-segments', (e) => {
                const n = (e.detail && e.detail.count) || 0;
                this.doneSegments += n;
                this.updateSpeedAndEta();
            });

            window.addEventListener('update-progress-batches', (e) => {
                if (e.detail) {
                    this.batchesDone = e.detail.done;
                    this.batchesTotal = e.detail.total;
                    this.updateSpeedAndEta();
                }
            });

            window.addEventListener('trigger-translation-start', (e) => {
                this.startTimer(e.detail.totalSegments, e.detail.totalPages, e.detail.targetPages);
                this.usage = null;
                clearInterval(this._tickTimer);
                this._tickTimer = setInterval(() => { this.elapsedTick = this.startTime ? (Date.now() - this.startTime) / 1000 : 0; }, 1000);
            });

            window.addEventListener('update-usage', (e) => {
                this.usage = e.detail || null;
            });

            window.addEventListener('trigger-translation-finished', () => {
                this.stopTimer();
                clearInterval(this._tickTimer);
            });

            // End-of-run summary toast: time, tokens, estimated cost
            window.addEventListener('translation-summary', (e) => {
                const d = e.detail || {};
                if (d.cancelled) return;
                const i18n = Alpine.store('i18n');
                const parts = [
                    rtFormat.duration(d.seconds),
                    rtFormat.tokens((d.prompt_tokens || 0) + (d.completion_tokens || 0)) + ' tokens',
                ];
                if (window.rtShowCost !== false) parts.push('~' + rtFormat.cost(d.cost_usd));
                window.showToast(i18n.translate('run_summary', { details: parts.join(' · '), segments: rtFormat.int(d.segments) }), 'success', 9000);
            });
        },

        initializeBounds(totalPages, totalSegments) {
            this.totalPages = totalPages;
            this.donePages = 0;
            this.totalSegments = totalSegments;
            this.doneSegments = 0;
            this.batchesDone = 0;
            this.batchesTotal = 0;
            this.startTime = null;
            this.speed = 0;
            this.eta = '';
            this.targetPages = null;
        },

        startTimer(totalSegments, totalPages, targetPages) {
            this.totalSegments = totalSegments;
            this.doneSegments = 0;
            this.startTime = Date.now();
            this.eta = Alpine.store('i18n').translate('calc_status');

            // ── RANGE BOUNDS RESOLUTION ──
            this.targetPages = targetPages; // Array of zero-based physical indices, e.g. [0, 4]
            if (targetPages && Array.isArray(targetPages)) {
                this.totalPages = targetPages.length;
            } else {
                this.totalPages = totalPages;
            }
            this.donePages = 0;
        },

        /** One-line live statistics: elapsed · remaining · tokens · cost */
        getUsageLine() {
            const i18n = Alpine.store('i18n');
            const parts = [];
            const elapsed = this.usage ? Math.max(this.usage.elapsed, this.elapsedTick) : this.elapsedTick;
            if (this.startTime || this.usage) parts.push('⏱ ' + rtFormat.duration(elapsed));
            if (this.usage && this.usage.eta !== null && this.startTime) {
                parts.push(i18n.translate('usage_remaining', { time: rtFormat.duration(this.usage.eta) }));
            }
            if (this.usage) {
                parts.push(rtFormat.tokens(this.usage.promptTokens + this.usage.completionTokens) + ' tokens (' +
                    rtFormat.tokens(this.usage.promptTokens) + ' ' + i18n.translate('usage_in') + ' / ' +
                    rtFormat.tokens(this.usage.completionTokens) + ' ' + i18n.translate('usage_out') + ')');
                if (window.rtShowCost !== false) parts.push('~' + rtFormat.cost(this.usage.costUsd));
            }
            return parts.join('   ·   ');
        },

        getModelLabel() {
            return this.usage && this.usage.model ? this.usage.model : '';
        },

        stopTimer() {
            this.startTime = null;
            this.eta = Alpine.store('i18n').translate('finished_status');
        },

        /**
         * Sets relative page progress dynamically.
         * Maps physical 1-based page numbers back to range sequential steps.
         */
        setPage(physicalPageNum) {
            if (this.targetPages && Array.isArray(this.targetPages)) {
                // Convert to 0-based index
                const actualPageIdx = physicalPageNum - 1;
                const seqIdx = this.targetPages.indexOf(actualPageIdx);
                if (seqIdx !== -1) {
                    this.donePages = seqIdx + 1;
                } else {
                    this.donePages = Math.min(physicalPageNum, this.totalPages);
                }
            } else {
                this.donePages = physicalPageNum;
            }
        },

        setBatches(done, total) {
            this.batchesDone = done;
            this.batchesTotal = total;
            this.updateSpeedAndEta();
        },

        incrementSegment() {
            this.doneSegments++;
            this.updateSpeedAndEta();
        },

        getPagesPercent() {
            return this.totalPages > 0 ? (this.donePages / this.totalPages) * 100 : 0;
        },

        getSegmentsPercent() {
            return this.totalSegments > 0 ? (this.doneSegments / this.totalSegments) * 100 : 0;
        },

        getPercentText() {
            if (this.totalSegments === 0) return '';
            return Math.round(this.getSegmentsPercent()) + '%';
        },

        updateSpeedAndEta() {
            if (!this.startTime || this.doneSegments === 0) return;

            const elapsedSeconds = (Date.now() - this.startTime) / 1000;
            this.speed = this.doneSegments / Math.max(elapsedSeconds, 0.1);

            const remainingSegments = this.totalSegments - this.doneSegments;
            const remainingSeconds = remainingSegments / Math.max(this.speed, 0.001);

            if (this.doneSegments >= this.totalSegments) {
                this.stopTimer();
                return;
            }

            const mins = Math.floor(remainingSeconds / 60);
            const secs = Math.floor(remainingSeconds % 60);

            const i18n = Alpine.store('i18n');
            this.eta = mins > 0
                ? i18n.translate('range_duration_mins_secs', { mins, secs })
                : i18n.translate('range_duration_secs', { secs });
        },

        getBatchSpeedLabel() {
            if (this.totalSegments === 0 || this.doneSegments >= this.totalSegments) return '';
            const i18n = Alpine.store('i18n');
            const batchLabel = this.batchesTotal
                ? i18n.translate('batch_info_msg', { done: this.batchesDone, total: this.batchesTotal })
                : '';
            // Speed/ETA come from the backend (see getUsageLine): batch counter only here
            return batchLabel;
        }
    };
}