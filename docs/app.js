/**
 * RockTranslate — High-Fidelity Scientific Translation Engine
 * Path: docs/app.js
 * 
 * Interactive Engine:
 * - Theme Switcher (Blanc Cassé / Dark Obsidian)
 * - Interactive Comparison Showcase (Dynamic tab switching + image switcher)
 * - Lightbox modal zoom for paper comparisons
 * - Testimonial category filters
 * - Dynamic CLI typewriter & interactive tabs
 * - Copy-to-clipboard with toast feedback
 * - FAQ accordion toggling
 */

document.addEventListener('DOMContentLoaded', () => {

    // ── 1. THEME SWITCHER (Blanc Cassé / Dark Obsidian) ──
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const themeIcon = document.getElementById('theme-icon');
    
    // Check saved theme or default to light (Blanc Cassé)
    const savedTheme = localStorage.getItem('rocktranslate_theme') || 'light';
    setTheme(savedTheme);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('rocktranslate_theme', theme);
        if (themeIcon) {
            if (theme === 'dark') {
                // Moon / Sun icon toggle
                themeIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />`;
                themeToggleBtn.setAttribute('title', 'Switch to light mode (Alabaster)');
            } else {
                themeIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />`;
                themeToggleBtn.setAttribute('title', 'Switch to dark mode (Obsidian)');
            }
        }
    }

    // ── 2. NAVBAR SCROLL ELEVATION ──
    const navbar = document.querySelector('.navbar');
    if (navbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 25) {
                navbar.classList.add('scrolled');
            } else {
                navbar.classList.remove('scrolled');
            }
        }, { passive: true });
    }

    // ── 3. INTERACTIVE SHOWCASE COMPARISON TABS ──
    const showcaseTabs = document.querySelectorAll('.showcase-tab-btn');
    const showcaseImg = document.getElementById('showcase-main-img');
    const showcaseTitle = document.getElementById('showcase-meta-title');
    const showcaseDesc = document.getElementById('showcase-meta-desc');
    const badgeLang = document.getElementById('badge-lang');
    const badgeFormat = document.getElementById('badge-format');
    const badgeExpansion = document.getElementById('badge-expansion');

    const showcaseData = {
        fr: {
            title: "English to French — Elsevier Earth-Sciences Multi-Column",
            desc: "Full stratigraphic diagram retention, precise geological nomenclature, and auto-scaled double columns without paragraph overlapping.",
            img: "assets/readme_comparison_en_to_fr.png",
            lang: "English → French",
            format: "Elsevier Double-Column",
            expansion: "+22% Word Expansion Managed"
        },
        spa: {
            title: "English to Spanish — Elsevier Complex Layout & Headers",
            desc: "Zero-drift reconstruction of publisher mastheads, author affiliations, and nested subheadings under high character count variance.",
            img: "assets/readme_comparison_en_to_spa.png",
            lang: "English → Spanish",
            format: "Elsevier Standard",
            expansion: "+18% Word Expansion Managed"
        },
        jn: {
            title: "English to Japanese — Attention Is All You Need (arXiv)",
            desc: "Flawless rendering of multi-head attention equations, CJK typography proportions, and vertical/horizontal glyph alignment.",
            img: "assets/readme_comparison_en_to_jn.png",
            lang: "English → Japanese (CJK)",
            format: "arXiv Two-Column AI Paper",
            expansion: "Double-Byte Glyphs Scaled"
        },
        ge: {
            title: "English to German — Elsevier Mechanics Tables & Vectors",
            desc: "Handling high-density German compound nouns (+30% expansion) while keeping mathematical equations and tabular borders completely intact.",
            img: "assets/readme_comparison_en_to_ge.png",
            lang: "English → German",
            format: "Elsevier Tabular Layout",
            expansion: "+29% Word Expansion Managed"
        }
    };

    if (showcaseTabs.length > 0) {
        showcaseTabs.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetKey = btn.getAttribute('data-showcase');
                const data = showcaseData[targetKey];
                if (!data) return;

                // Update active tab button
                showcaseTabs.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Smooth fade transition on image
                if (showcaseImg) {
                    showcaseImg.style.opacity = '0.3';
                    showcaseImg.style.transform = 'scale(0.99)';

                    setTimeout(() => {
                        showcaseImg.src = data.img;
                        showcaseImg.alt = data.title;
                        showcaseTitle.textContent = data.title;
                        showcaseDesc.textContent = data.desc;
                        badgeLang.textContent = data.lang;
                        badgeFormat.textContent = data.format;
                        badgeExpansion.textContent = data.expansion;

                        showcaseImg.style.opacity = '1';
                        showcaseImg.style.transform = 'scale(1)';
                    }, 150);
                }
            });
        });
    }

    // ── 4. LIGHTBOX IMAGE ZOOM INSPECTOR ──
    const lightbox = document.getElementById('image-lightbox');
    const lightboxImg = document.getElementById('lightbox-img');
    const lightboxClose = document.getElementById('lightbox-close');
    const showcaseViewer = document.getElementById('showcase-viewer');

    if (showcaseViewer && lightbox && lightboxImg) {
        showcaseViewer.addEventListener('click', () => {
            const currentImg = document.getElementById('showcase-main-img');
            if (currentImg) {
                lightboxImg.src = currentImg.src;
                lightbox.classList.add('active');
                document.body.style.overflow = 'hidden';
            }
        });

        const closeLightbox = () => {
            lightbox.classList.remove('active');
            document.body.style.overflow = '';
        };

        if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
        lightbox.addEventListener('click', (e) => {
            if (e.target === lightbox) closeLightbox();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && lightbox.classList.contains('active')) {
                closeLightbox();
            }
        });
    }

    // ── 5. TESTIMONIALS CATEGORY FILTERING ──
    const filterChips = document.querySelectorAll('.filter-chip');
    const testimonialCards = document.querySelectorAll('.testimonial-card');

    if (filterChips.length > 0) {
        filterChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const category = chip.getAttribute('data-filter');

                filterChips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');

                testimonialCards.forEach(card => {
                    const cardCat = card.getAttribute('data-category');
                    if (category === 'all' || cardCat === category) {
                        card.style.display = 'flex';
                        card.style.opacity = '0';
                        card.style.transform = 'translateY(12px)';
                        setTimeout(() => {
                            card.style.opacity = '1';
                            card.style.transform = 'translateY(0)';
                        }, 50);
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        });
    }

    // ── 6. DEVELOPER TERMINAL INTERACTIVE PLAYGROUND ──
    const terminalTabBtns = document.querySelectorAll('.terminal-tab-btn');
    const terminalBodies = document.querySelectorAll('.terminal-tab-content');
    const terminalCliBody = document.getElementById('terminal-cli-content');
    const copyCommandBtn = document.getElementById('btn-copy-terminal');

    const cliCommands = [
        { type: 'input', text: 'pip install rocktranslate' },
        { type: 'output', text: 'Collecting rocktranslate...' },
        { type: 'output', text: 'Installing pdf2htmlEX-windows, beautifulsoup4, litellm...' },
        { type: 'success', text: 'Successfully installed rocktranslate-2.0.2' },
        { type: 'input', text: 'rocktranslate article_geology.pdf --target-lang French --model gemini/gemini-3.8-flash' },
        { type: 'output', text: '[INFO] Initializing lazy geometric parser...' },
        { type: 'output', text: '[INFO] DOM extracted (42 pages, 18 tables, 62 equations)' },
        { type: 'output', text: '[INFO] Translating with context-aware font scaling...' },
        { type: 'output', text: '[INFO] Generating high-DPI vector print via headless browser...' },
        { type: 'success', text: '[SUCCESS] Pixel-perfect PDF created: "article_geology_fr.pdf"' }
    ];

    let cliSimulationRan = false;

    async function runTypewriterSimulation() {
        if (!terminalCliBody || cliSimulationRan) return;
        cliSimulationRan = true;
        terminalCliBody.innerHTML = '';

        for (let item of cliCommands) {
            const line = document.createElement('div');
            line.className = 'code-line';
            terminalCliBody.appendChild(line);

            if (item.type === 'input') {
                const prompt = document.createElement('span');
                prompt.className = 'code-prompt';
                prompt.textContent = '$ ';
                line.appendChild(prompt);

                const textSpan = document.createElement('span');
                line.appendChild(textSpan);

                const cursor = document.createElement('span');
                cursor.className = 'blink-cursor';
                line.appendChild(cursor);

                for (let i = 0; i < item.text.length; i++) {
                    textSpan.textContent += item.text[i];
                    await new Promise(r => setTimeout(r, 20 + Math.random() * 20));
                }

                cursor.remove();
                await new Promise(r => setTimeout(r, 350));
            } else {
                const outSpan = document.createElement('span');
                if (item.type === 'success') {
                    outSpan.className = 'code-string';
                    outSpan.style.fontWeight = 'bold';
                } else {
                    outSpan.className = 'code-comment';
                }
                outSpan.textContent = item.text;
                line.appendChild(outSpan);
                await new Promise(r => setTimeout(r, 180));
            }
        }

        // Final active prompt cursor
        const endLine = document.createElement('div');
        endLine.className = 'code-line';
        endLine.innerHTML = '<span class="code-prompt">$ </span><span class="blink-cursor"></span>';
        terminalCliBody.appendChild(endLine);
    }

    // Trigger CLI typewriter when scrolled into view
    const terminalEl = document.querySelector('.code-terminal');
    if (terminalEl && 'IntersectionObserver' in window) {
        const terminalObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !cliSimulationRan) {
                    runTypewriterSimulation();
                    terminalObserver.unobserve(terminalEl);
                }
            });
        }, { threshold: 0.25 });
        terminalObserver.observe(terminalEl);
    }

    // Tab switcher between CLI, Python API, and Ollama
    if (terminalTabBtns.length > 0) {
        terminalTabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTab = btn.getAttribute('data-tab');

                terminalTabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                terminalBodies.forEach(body => {
                    if (body.id === `terminal-${targetTab}-content`) {
                        body.style.display = 'block';
                    } else {
                        body.style.display = 'none';
                    }
                });

                if (targetTab === 'cli' && !cliSimulationRan) {
                    runTypewriterSimulation();
                }
            });
        });
    }

    // Copy to clipboard button in terminal
    if (copyCommandBtn) {
        copyCommandBtn.addEventListener('click', () => {
            const activeTab = document.querySelector('.terminal-tab-btn.active');
            let textToCopy = 'pip install rocktranslate';

            if (activeTab) {
                const tabKey = activeTab.getAttribute('data-tab');
                if (tabKey === 'python') {
                    textToCopy = `from rocktranslate import RockTranslator\n\ntranslator = RockTranslator(model="gemini/gemini-3.8-flash", target_lang="French")\ntranslator.translate("paper.pdf", "paper_fr.pdf")`;
                } else if (tabKey === 'ollama') {
                    textToCopy = `ollama run llama4\nrocktranslate paper.pdf --model ollama/llama4 --target-lang Spanish`;
                }
            }

            navigator.clipboard.writeText(textToCopy).then(() => {
                showToast("Code copied to clipboard!");
            }).catch(() => {
                showToast("Failed to copy to clipboard.");
            });
        });
    }

    // ── 7. FAQ ACCORDION TOGGLING ──
    const faqItems = document.querySelectorAll('.faq-item');
    if (faqItems.length > 0) {
        faqItems.forEach(item => {
            const questionBtn = item.querySelector('.faq-question');
            if (questionBtn) {
                questionBtn.addEventListener('click', () => {
                    const isOpen = item.classList.contains('open');
                    // Close others
                    faqItems.forEach(other => other.classList.remove('open'));
                    // Toggle current
                    if (!isOpen) {
                        item.classList.add('open');
                    }
                });
            }
        });
    }

    // ── 8. ONE-CLICK INSTALL COMMAND COPY PILL ──
    const pipPills = document.querySelectorAll('.cta-package-pill');
    pipPills.forEach(pill => {
        pill.addEventListener('click', () => {
            navigator.clipboard.writeText('pip install rocktranslate').then(() => {
                showToast("Command 'pip install rocktranslate' copied!");
            });
        });
    });

    // ── 9. TOAST NOTIFICATION UTILITY ──
    function showToast(message) {
        let toast = document.querySelector('.toast-notice');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'toast-notice';
            document.body.appendChild(toast);
        }

        toast.textContent = message;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, 2600);
    }

});