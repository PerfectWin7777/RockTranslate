
# <img src="src/rocktranslate/assets/rocktranslate_icon.png" width="48" align="center" alt="RockTranslate Icon" /> RockTranslate

<p align="center">
  <img src="src/rocktranslate/assets/RockTranslate_logo.png" width="480" alt="RockTranslate Logo" />
</p>

<p align="center">
  <strong>High-Fidelity AI Layout-Preserved PDF Translator</strong>
</p>

<p align="center">
  <!-- High-visibility dynamic download badge -->
  <a href="https://github.com/PerfectWin7777/RockTranslate/releases/download/v1.0.0/RockTranslate_Setup_v1.0.0.exe">
    <img src="https://img.shields.io/badge/Download-Windows%20GUI%20Installer-blue?style=for-the-badge&logo=windows&logoColor=white" alt="Download Windows GUI Installer" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Python-3.9+-green.svg" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Supported Platforms" />
</p>

---

### 📥 [Click here to download the standalone Windows Desktop GUI Installer (.exe)](https://github.com/PerfectWin7777/RockTranslate/releases/tag/v1.0.0-beta/RockTranslate_Setup_v1.0.0.exe)

---

## 1. Introduction & Origin Story

> *"RockTranslate breaks the limits of traditional PDF translation. By combining advanced LLMs with high-fidelity geometric DOM mapping, it reconstructs complex scientific papers from publishers like Elsevier and Springer into completely native, translated PDFs."*

### Our Story: Bridging the Academic Inequality Gap

Scientific and academic research is a global endeavor, yet the vast majority of high-impact literature is published in English. For students and researchers in developing nations, particularly in Africa and Cameroon, accessing, translating, and fully understanding these highly complex documents poses a massive challenge [1]. 

Traditional translation tools are either:
1.  **Prohibitively expensive** or heavily restricted by paid subscription tiers (e.g., DeepL, Google Translate).
2.  **Lacking visual layout preservation** (e.g., standard text extractors, legacy translation proxies), rendering complex formulas, double-column structures, and tables completely unreadable [2].

**RockTranslate** was born out of academic necessity, created by students facing these exact barriers. It is designed to be a fully accessible, local-first, high-fidelity alternative that allows any researcher, anywhere, to translate academic PDFs without losing their original layout—empowering global education without financial borders [1].

---

## 2. Key Features

RockTranslate is a desktop application designed for translating scientific, technical, and academic PDF documents while preserving their original structure, formatting, figures, tables, and visual layout.

Built with a local-first architecture, RockTranslate prioritizes performance, reliability, and user control. The application combines advanced document analysis, intelligent translation workflows, and high-fidelity PDF reconstruction to deliver professional-quality results.

*   **Layout-Preserved PDF Translation:** Retains the exact geometry, columns, margins, and alignment of the original document [2].
*   **Scientific and Technical Document Support:** Specially designed to handle mathematical formulas, indices, equations, and proper academic nomenclature.
*   **High-Fidelity PDF Reconstruction:** Preserves figures, images, and tables in their original spatial coordinates.
*   **Fast Desktop Performance:** Employs parallel and asynchronous processing to deliver translations without blocking user interfaces [1].
*   **Lightweight and Responsive User Experience:** Optimized loading speeds and visual feedback indicators.
*   **Privacy-Conscious Workflow:** Supports offline and local-first execution via local LLMs (Ollama) to guarantee complete data privacy.
*   **Open-Source and Community-Driven:** Built entirely on open-source foundations, giving control back to the scientific community.

---


## 3. Installation

Choose the installation method that best suits your requirements:

### A. Package Installation (via pip)
RockTranslate is officially published on PyPI. You can install the core lightweight library (CLI & API only) or include full desktop GUI support:

**For CLI & Programmatic API only (Lightweight, No GUI):**
```bash
pip install rocktranslate
```
**For the full Desktop Graphical User Interface (GUI):**
```bash
pip install "rocktranslate[gui]"
```

### B. Development Installation (via Git)
For the most up-to-date features, or to run the application directly from source:
```bash
# Clone the repository
git clone https://github.com/PerfectWin7777/RockTranslate.git
cd RockTranslate

# Install dependencies and the package in editable mode
pip install -e .
```

### C. Direct Remote Install
You can also install the development version directly from GitHub without cloning the repository manually:
```bash
pip install git+https://github.com/PerfectWin7777/RockTranslate.git
```

---

## 4. Visual Demonstration (Before & After)

### Real-Time Application Lifecycle
*The following animation demonstrates opening, rendering, and translating a multi-column paper dynamically:*

<p align="center">
  <img src=".github/assets/readme_animation.gif" width="800" alt="RockTranslate Application Demo" />
</p>

---

### 🔬 1. English to Spanish (Elsevier Double-Column Layout)
*Demonstrating perfect preservation of multi-column text flow, publisher headers, and author blocks.*

![English to Spanish Comparison](.github/assets/readme_comparison_en_to_spa.png)

*The original Elsevier double-column layout is fully retained with zero text-overlapping or margin drift.*

---

### 🧠 2. English to French (Attention Is All You Need — Abstract & Title)
*Demonstrating precise preservation of scientific structures, titles, and mathematical equations.*

![English to French Comparison](.github/assets/readme_comparison_en_to_fr.png)

*Mathematical formulas, paragraph flows, and proper academic register remain completely intact.*

---

### 🌸 3. English to Japanese (Attention Is All You Need — Paragraph Flow)
*Demonstrating robust handling of double-byte CJK characters without vertical line collapses or overlapping.*

![English to Japanese Comparison](.github/assets/readme_comparison_en_to_jn.png)

*Japanese Kanji and Kana characters are rendered cleanly with proportional horizontal scaling.*

---

### 🌸 4. English to German (Elsevier Double-Column Layout— Paragraph Flow and Table)
*Demonstrating robust preservation of tables and math formulas in a double-column layout..*

![English to German Comparison](.github/assets/readme_comparison_en_to_ge.png)

*Clarity of paragraphs, tables and styles, preservation of mathematical formulas.*

---

## 5. The Three Versions

RockTranslate provides three entry points to support any workflow:

### A. Graphical User Interface (GUI)
A responsive desktop application featuring:
*   Synchronized dual-pane viewports (Original PDF vs. Live Translated HTML) [2].
*   Real-time zoom sliders and page navigation.
*   Visual shimmer skeleton loaders and real-time status bars [1, 2].

### 📥 [Click here to download the standalone Windows Desktop GUI Installer (.exe)](https://github.com/PerfectWin7777/RockTranslate/releases/tag/v1.0.0-beta/RockTranslate_Setup_v1.0.0.exe)

### B. Command-Line Interface (CLI)
A lightweight execution engine that can be run globally from the terminal once installed [3].

#### Usage Examples:
1.  **Translate to French (default) using the default Gemini model:**
    ```bash
    rocktranslate article_scientifique.pdf -l French
    ```
2.  **Translate to Spanish and save to a custom output file:**
    ```bash
    rocktranslate paper.pdf -l Spanish -o report_es.pdf
    ```
3.  **Translate to German using OpenAI with an explicit API key:**
    ```bash
    rocktranslate document.pdf -m openai/gpt-4o-mini -k YOUR_OPENAI_KEY -l German
    ```
4.  **Run fully local translation using Ollama (no API key required):**
    ```bash
    rocktranslate document.pdf -m ollama/llama3 -l French
    ```

---

### 💡 Dynamic Model Routing & Frontier Models Guidance

#### 1. Model Naming Convention (LiteLLM Integration)
RockTranslate inherits its entire model routing architecture directly from **LiteLLM**. All model identifiers passed through the `-m / --model` CLI flag (or through the API) must strictly follow the standard `provider/model_name` syntax. 

Both the provider prefix and the model name must match the exact naming conventions defined in the [LiteLLM Supported Providers & Models Documentation](https://docs.litellm.ai/docs/providers).

#### 2. Why Frontier Models are Essential for Perfect Visual Layouts
While local or lightweight models function perfectly, we highly recommend using advanced **frontier models**—such as **Gemini 3.5 Flash**, **GPT 5.5**, **Claude 4.X**, **DeepSeek V4**, **Kimi K2.6**, or **GLM 5.5 ; Any other open-source LLM provider**—for complex scientific papers. 

*   **Instruction-Following & Tag Integrity:** Frontier models possess superior reasoning capabilities. They strictly preserve nested XML style tags (like `<color_HEX>`) and structural JSON mapping arrays, allowing the renderer to position text segments with pixel-perfect accuracy.
*   **Academic Register & Context:** They avoid literal, broken word-by-word translations of fragmented segments. Instead, they understand the global paragraph context, translating complex double-column academic layouts into natural scientific prose.


### C. API Developer Library
Integrate layout-preserved document translation directly into your Python scripts or data pipelines.

#### Programmatic Integration Scenarios:
```python
import os
from rocktranslate import RockTranslator

# Ensure a sample file is present before initiating diagnostic runs
sample_pdf = "article_scientifique.pdf"

if not os.path.exists(sample_pdf):
    print(f"Sample file '{sample_pdf}' not found. Please provide a valid PDF.")
else:
    # ──────────────────────────────────────────────────────────────────────
    # SCENARIO 1: Basic Translation (Using Google Gemini with environment key)
    # ──────────────────────────────────────────────────────────────────────
    # Automatically searches for GEMINI_API_KEY inside system environment variables.
    # Uses the advanced Gemini 3.5 Flash model for superior layout preservation.
    translator_gemini = RockTranslator(
        model="gemini/gemini-3.5-flash",
        target_lang="Spanish"
    )
    
    # Executes translation, saving the file to '[article_scientifique]_translated.pdf'
    success_gemini = translator_gemini.translate(input_pdf_path=sample_pdf)
    print(f"Scenario 1 complete. Success: {success_gemini}")

    # ──────────────────────────────────────────────────────────────────────
    # SCENARIO 2: Custom Output Path and Language Customization
    # ──────────────────────────────────────────────────────────────────────
    translator_custom = RockTranslator(
        model="gemini/gemini-3.5-flash",
        target_lang="German"
    )
    
    # Translates to German and writes output to a custom specified path
    custom_output = "results/german_report.pdf"
    os.makedirs("results", exist_ok=True)
    
    success_custom = translator_custom.translate(
        input_pdf_path=sample_pdf,
        output_pdf_path=custom_output
    )
    print(f"Scenario 2 complete. Translated PDF written to: {custom_output} (Success: {success_custom})")

    # ──────────────────────────────────────────────────────────────────────
    # SCENARIO 3: Frontier Provider (OpenAI GPT 5.5) with Explicit API Key
    # ──────────────────────────────────────────────────────────────────────
    # Explicit credentials pass overrides local environment configurations.
    # We route the request using the exact LiteLLM naming convention (provider/model_name).
    # Learn more at: https://docs.litellm.ai/docs/providers
    translator_openai = RockTranslator(
        model="openai/gpt-5.5",
        api_key="sk-your-openai-api-key-here",  # Replace with a valid credentials key
        target_lang="Italian",
        temperature=0.3  # Lower temperature for more rigid, literal academic translation
    )
    
    # success_openai = translator_openai.translate(input_pdf_path=sample_pdf)
    print("Scenario 3 configured. (Run skipped to avoid credential errors.)")

    # ──────────────────────────────────────────────────────────────────────
    # SCENARIO 4: Fully Local and Offline Translation (Using Ollama)
    # ──────────────────────────────────────────────────────────────────────
    # No API keys or remote servers required. Ensure Ollama is running on the host machine.
    translator_local = RockTranslator(
        model="ollama/llama3",
        target_lang="French",
        custom_base_url="http://localhost:11434"  # Default local Ollama gateway port
    )
    
    # success_local = translator_local.translate(input_pdf_path=sample_pdf)
    print("Scenario 4 configured for local offline execution.")
```

---

## 6. Known Limitations & Roadmap (TODO)

### Current Limitations:
*   **The LaTeX FontForge Crash (Windows):** Older standalone versions of `pdf2htmlEX` on Windows occasionally experience segmentation faults or infinite loops when compiling complex, customized LaTeX mathematical fonts (Type-1 vector fonts) [2.2.6].
    *   *Our Solution:* We have implemented a robust Windows crash preventer (`SetErrorMode`) and a strict 30-second subprocess timeout. If a compilation hangs, RockTranslate instantly terminates the process and fails gracefully in under 50ms without freezing the UI [1].

### Roadmap & Future TODOs:
*   [ ] **Bilingual Translation Memory Export (TMX / JSON):** Add a button inside the document properties modal to let users download a clean bilingual parallel aligned sheet (.json/.tmx) of the translated paper.
*   [ ] **Local PDF.js Night & Sepia Mode:** Implement visual color inversion overlays inside the native PDF.js iframe, allowing users to comfortably study original double-column layouts in low-light environments.
*   [ ] **Scanned PDF Support (Local OCR Fallback):** Integrate a lightweight local OCR pipeline (e.g., Tesseract wrapper) to automatically recognize and translate text flattened inside scanned, image-only academic PDFs.
*   [ ] **Automatic Fallback to Serverless Cloud Conversion:** Integrate an optional, free, or self-hosted serverless cloud rendering API (using the official Docker Linux image) to handle complex LaTeX papers without any local system limitations [1, 2].
*   [ ] **Concurrent Batch Translation:** Implement parallel API calls (limited to 3 concurrent requests to respect free-tier quotas) to speed up translation times by 3x [1].

---

## 7. Contributing & Community Support

We believe in making scientific literature universally accessible and welcome contributions from researchers, developers, and educators. Here is how you can help advance the project:

*   **Core UI Refactoring:** Help us migrate from the resource-intensive PyQt6/QWebEngine setup to a lightweight `pywebview` client.
*   **Bug Reports & Edge Cases:** Found a PDF with highly complex LaTeX layout issues? Open an issue and upload the file (or a sample page) so we can optimize our BeautifulSoup parser rules.
*   **Translation & Localization:** Contribute internationalization files (`.qm`/`.ts` translations) to make the user interface available in more languages.
*   **Prompt Optimization:** Help us refine the instructions in `prompts.py` to further improve terminology preservation and tag alignment across different languages.

To contribute, please fork the repository, make your changes in a dedicated branch, and submit a pull request. For major architectural modifications, feel free to open an issue first to discuss your ideas with the core maintainers.

---

## 8. Acknowledgements & Credits

RockTranslate stands on the shoulders of giants. We would like to express our deepest gratitude to the open-source projects that made this tool possible:
*   **pdf2htmlEX:** The geometric engine used to compile PDF structures into HTML [2.2.1] ([GitHub](https://github.com/pdf2htmlEX/pdf2htmlEX)).
*   **Poppler & FontForge:** The underlying vector engines driving pdf2htmlEX [3.2.4] ([Poppler Website](https://poppler.freedesktop.org/) | [FontForge Website](https://fontforge.org/)).
*   **LiteLLM:** The multi-provider AI routing wrapper [2.3.1] ([Official Documentation](https://docs.litellm.ai/)).
*   **BeautifulSoup4 & lxml:** Driving high-speed, programmatic DOM analysis ([BeautifulSoup Documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) | [lxml Website](https://lxml.de/)).