/**
 * RockTranslate — Progress Panel Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/progress.js
 * 
 * Manages reactive translation progress and calculates speeds and ETAs.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.0
 */

function progressController() {
    return {
        // Toggle from the top dropdown View menu
        visible: true,

        // Total page and segment metrics
        totalPages: 0,
        donePages: 0,
        totalSegments: 0,
        doneSegments: 0,
        batchesDone: 0,
        batchesTotal: 0,

        // Calculation variables
        startTime: null,
        speed: 0,
        eta: '',

        init() {
            // Listen to show/hide toggles from the top View menu
            window.addEventListener('trigger-toggle-progress', (e) => {
                this.visible = e.detail.visible;
            });

            // Set boundaries when a PDF is fully loaded into workspace viewports
            window.addEventListener('document-ready', (e) => {
                this.initializeBounds(e.detail.totalPages, e.detail.totalSegments);
            });

            // --- PYTHON WORKER SIGNALS LISTENERS (SLOTS EQUIVALENTS) ---
            window.addEventListener('update-progress-page', (e) => {
                if (e.detail && e.detail.page) {
                    this.donePages = e.detail.page;
                }
            });

            window.addEventListener('update-progress-segment', () => {
                this.incrementSegment();
            });

            window.addEventListener('update-progress-batches', (e) => {
                if (e.detail) {
                    this.batchesDone = e.detail.done;
                    this.batchesTotal = e.detail.total;
                    this.updateSpeedAndEta();
                }
            });

            window.addEventListener('trigger-translation-start', (e) => {
                this.startTimer(e.detail.totalSegments);
            });

            window.addEventListener('trigger-translation-finished', () => {
                this.stopTimer();
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
        },

        startTimer(totalSegments) {
            this.totalSegments = totalSegments;
            this.doneSegments = 0;
            this.startTime = Date.now();
            this.eta = Alpine.store('i18n').translate('calc_status');
        },

        stopTimer() {
            this.startTime = null;
            this.eta = Alpine.store('i18n').translate('finished_status');
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
            const speedLabel = this.speed > 0
                ? i18n.translate('speed_info_msg', { speed: this.speed.toFixed(1) })
                : '';
            return batchLabel && speedLabel ? `${batchLabel} | ${speedLabel}` : batchLabel || speedLabel;
        }
    };
}