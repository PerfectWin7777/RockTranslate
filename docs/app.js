/**
 * RockTranslate — Landing Page Interactive Engine
 * Path: docs/js/app.js
 * 
 * Manages same-origin scroll reveals, dynamic navbar blurring, 
 * and realistic typewriter CLI terminal simulations.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.0
 */

document.addEventListener('DOMContentLoaded', () => {

    // ── 1. DYNAMIC NAVBAR SCROLL BLUR ──
    const nav = document.querySelector('.glass-nav');
    if (nav) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 20) {
                nav.style.background = 'rgba(7, 10, 19, 0.88)';
                nav.style.boxShadow = '0 10px 30px rgba(0, 0, 0, 0.3)';
                nav.style.height = '64px'; // Slightly compress height on scroll for premium feel
            } else {
                nav.style.background = 'rgba(7, 10, 19, 0.7)';
                nav.style.boxShadow = 'none';
                nav.style.height = '70px';
            }
        });
    }

    // ── 2. HIGH-PERFORMANCE SCROLL REVEAL (Intersection Observer) ──
    const revealElements = document.querySelectorAll('.glass-card, .developers-terminal, .developers-info');

    if ('IntersectionObserver' in window) {
        revealElements.forEach(el => {
            // Apply initial hidden states programmatically to prevent Flash of Unstyled Content (FOUC)
            el.style.opacity = '0';
            el.style.transform = 'translateY(30px)';
            el.style.transition = 'opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)';

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        el.style.opacity = '1';
                        el.style.transform = 'translateY(0)';
                        observer.unobserve(el); // Fire only once
                    }
                });
            }, {
                threshold: 0.1,
                rootMargin: '0px 0px -50px 0px'
            });

            observer.observe(el);
        });
    } else {
        // Fallback for older legacy browsers
        revealElements.forEach(el => {
            el.style.opacity = '1';
        });
    }

    // ── 3. INTERACTIVE CLI TERMINAL TYPEWRITER SIMULATION ──
    const terminal = document.querySelector('.developers-terminal');
    const terminalBody = document.querySelector('.terminal-body');

    if (terminal && terminalBody) {
        let terminalStarted = false;

        // Define the lines to type and their delay behaviors
        const consoleLines = [
            { type: 'input', text: 'pip install rocktranslate' }, // 
            { type: 'output', text: 'Installing beautifulsoup4, litellm, lxml...' },
            { type: 'output', text: 'Successfully installed rocktranslate-1.0.0' },
            { type: 'input', text: 'rocktranslate paper.pdf --lang French' },
            { type: 'output', text: '[INFO] Initializing RockTranslate CLI...' },
            { type: 'output', text: '[INFO] Discovered browser: "chrome-headless-shell"' },
            { type: 'output', text: '[INFO] Rebuilding HTML DOM with translation overlays...' },
            { type: 'success', text: '[SUCCESS] Translated PDF saved at: "paper_translated.pdf"' }
        ];

        const runTerminalSimulation = async () => {
            // Clear the pre-rendered mockup layout
            terminalBody.innerHTML = '';

            for (let line of consoleLines) {
                const lineDiv = document.createElement('div');
                lineDiv.className = 'code-line';
                terminalBody.appendChild(lineDiv);

                if (line.type === 'input') {
                    // Create CLI command input structures
                    const prompt = document.createElement('span');
                    prompt.className = 'code-prompt';
                    prompt.textContent = '$ ';
                    lineDiv.appendChild(prompt);

                    const textSpan = document.createElement('span');
                    lineDiv.appendChild(textSpan);

                    const cursor = document.createElement('span');
                    cursor.className = 'blink-cursor';
                    cursor.textContent = '_';
                    lineDiv.appendChild(cursor);

                    // Typewriter character interpolation
                    for (let i = 0; i < line.text.length; i++) {
                        textSpan.textContent += line.text[i];
                        await new Promise(resolve => setTimeout(resolve, 35 + Math.random() * 30));
                    }

                    // Remove cursor once the line is completed
                    cursor.remove();
                    await new Promise(resolve => setTimeout(resolve, 500));
                } else {
                    // Instantly append log output lines with a subtle rendering pause
                    const outputSpan = document.createElement('span');
                    outputSpan.className = line.type === 'success' ? 'code-output' : 'code-comment';
                    if (line.type === 'success') {
                        outputSpan.style.color = 'var(--accent-green)';
                        outputSpan.style.fontWeight = 'bold';
                    }
                    outputSpan.textContent = line.text;
                    lineDiv.appendChild(outputSpan);

                    await new Promise(resolve => setTimeout(resolve, 300));
                }
            }

            // Append final active prompt blinking cursor
            const finalLine = document.createElement('div');
            finalLine.className = 'code-line';

            const prompt = document.createElement('span');
            prompt.className = 'code-prompt';
            prompt.textContent = '$ ';

            const cursor = document.createElement('span');
            cursor.className = 'blink-cursor';
            cursor.textContent = '_';

            finalLine.appendChild(prompt);
            finalLine.appendChild(cursor);
            terminalBody.appendChild(finalLine);
        };

        // Start terminal simulation only when it scrolls into view
        const terminalObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !terminalStarted) {
                    terminalStarted = true;
                    setTimeout(runTerminalSimulation, 600);
                    terminalObserver.unobserve(terminal);
                }
            });
        }, { threshold: 0.2 });

        terminalObserver.observe(terminal);

        // ── DYNAMIC TERMINAL TAB SWITCHING LOGIC ──
        const tabButtons = document.querySelectorAll('.terminal-tab');
        const tabContents = document.querySelectorAll('.tab-content');

        tabButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTab = btn.getAttribute('data-tab');

                // Toggle active states on tab buttons
                tabButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Toggle active states on tab body contents
                tabContents.forEach(content => {
                    if (content.getAttribute('id') === `terminal-${targetTab}`) {
                        content.style.display = 'block';
                        content.classList.add('active');

                        // Restart CLI typewriter simulation if clicking back to the CLI tab
                        if (targetTab === 'cli' && !terminalStarted) {
                            terminalStarted = true;
                            runTerminalSimulation();
                        }
                    } else {
                        content.style.display = 'none';
                        content.classList.remove('active');
                    }
                });
            });
        });
    }
});