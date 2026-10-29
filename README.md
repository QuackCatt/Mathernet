# Mathernet

[English](README.md) | [简体中文](README.zh-CN.md)

Mathernet is a local, AI-assisted formula learning workspace. Describe a formula in your own words, review the candidates, and add the right one to a visual knowledge map. You can also write study notes, review formulas, and explore the ideas behind them with AI.

Everything is managed in a web interface. You only use Terminal or Command Prompt to start the downloaded application; there is no separate installation step.

## System Requirements

- Python **3.11 or newer**.
- A current desktop browser (for example Safari, Chrome, Edge, or Firefox).
- One AI API key from either **OpenRouter** or **DeepSeek**.
- Internet access is required only when using AI features.
- Node.js, Docker, a database, and programming knowledge are not required.

Mathernet runs on **macOS**, **Windows 10/11**, and mainstream **Linux** desktops. It is designed for desktop browsers and does not include a mobile interface.

## Start Mathernet

Use the following complete flow every time. Mathernet is started directly from the downloaded folder and is not installed globally.

1. On GitHub, click **Code**, then click **Download ZIP**.
2. Unzip the downloaded file. Keep the unzipped project folder together; do not move only the `mathernet` or `run_mathernet.py` file out of it.
3. Open the unzipped project folder in Terminal or Command Prompt:
   - **macOS or Linux:** Open Terminal, type `cd ` with one space after it, drag the unzipped folder into the Terminal window, then press Enter.
   - **Windows:** Open the unzipped folder in File Explorer, type `cmd` in the File Explorer address bar, then press Enter.
4. Start Mathernet from inside that folder:
   - **macOS or Linux:**

     ```sh
     ./mathernet start
     ```

   - **Windows:**

     ```bat
     py .\run_mathernet.py start
     ```

     If `py` is not available, run `python .\run_mathernet.py start` instead.

5. Keep the Terminal or Command Prompt window open. Use the exact URL printed by Mathernet, such as `http://127.0.0.1:8765`, in your browser. Always use the URL shown on your screen instead of guessing the port.

Keep the folder prefix shown in the command. The `./` on macOS/Linux or `.\` on Windows ensures that the program inside the current downloaded folder is used. On macOS or Linux, if `./mathernet` reports a permission error, run `python3 mathernet start` instead.

To start Mathernet again later, open the same unzipped project folder and repeat steps 3–5. There is no separate installation or update command.

If the default port is already in use, Mathernet automatically selects the next available port and prints the new URL. To stop Mathernet, close the Terminal or Command Prompt window, or press `Control + C`.

## First-Time Setup

The AI provider settings open automatically the first time you use Mathernet.

1. Choose **OpenRouter** or **DeepSeek**.
2. Get an API key from the provider's official website.
3. Paste the API key into Mathernet.
4. Click **Save provider**.

Mathernet tests the connection automatically. When it is ready, the status light turns green and the settings window closes.

You only need to do this once. To change providers or keys later, click the **Settings** button in Mathernet. When you switch providers, enter the new provider's API key; Mathernet does not reuse the old one.

## Get an API Key

### OpenRouter

1. Open the [OpenRouter API Keys page](https://openrouter.ai/keys).
2. Sign in or create an OpenRouter account.
3. Click **Create Key**, give it a simple name such as `Mathernet`, and create the key.
4. Copy the full key immediately. OpenRouter may not display it again.
5. In Mathernet, select **OpenRouter**, paste the key, and click **Save provider**.

If you are unsure which model to use, keep the suggested model route. You can click **Load models** to see the model routes available to your OpenRouter account.

### DeepSeek

1. Open the [DeepSeek API Keys page](https://platform.deepseek.com/api_keys).
2. Sign in or create a DeepSeek account.
3. Create a new API key.
4. Copy the full key.
5. In Mathernet, select **DeepSeek**, paste the key, and click **Save provider**.

DeepSeek does not require you to enter a model ID. Mathernet selects the standard DeepSeek chat model automatically.

Your API key is stored only on your computer and is hidden after saving.

## Use Mathernet

### Create a Mind Map

Click **New mind map**, enter a name, and confirm. Each mind map is a separate workspace, so you can organize different courses or topics independently.

### Add a Formula

1. Enter a formula, formula name, or plain-language description in the top search box.
2. Wait for Mathernet to show up to five possible formulas.
3. Select the formula that best matches what you need.

Mathernet first checks your existing library. If the formula is already saved, it opens that formula instead of creating a duplicate.

### Read a Formula

Select a formula to open its details:

- **Overview** contains the formula and a short introduction.
- **Explore deeper** opens a longer explanation with useful context, stories, applications, and available sources when they can be found.
- **Learning** contains the study status and your personal study note.

To remove a formula, use the trash button on its card. This removes the card from every mind map and also deletes its saved deep dives, its saved introduction, and its relationships.

You can continue asking questions in the conversation box at the bottom of **Explore deeper**.

### Work with the Map

- Drag formulas to arrange the map.
- Drag two formulas close together and release to create a relationship.
- Drag the red scissors onto a relationship line to remove it. Its saved relationship deep dive is removed too.
- Drag the blue magnifier onto a relationship line to explore why the formulas connect.
- Click an empty part of the map to return to the full map view.

The top-right buttons collapse the left and right panels when you want more space.

## Privacy

- Formula cards, notes, mind maps, generated conversations, and API settings stay on your computer.
- Personal learning data is stored in the local `data` folder.
- API keys are stored locally and are never uploaded to GitHub.
- When you use AI features, the relevant formula text and questions are sent to the AI provider you selected. Your API key is sent only to that provider.
- Sources shown under **Explore deeper** are returned by the AI provider. Mathernet does not independently verify them. If the provider can search the web itself, it may use that search.

## Important

Mathernet is a study and organization tool. It does not solve graded assignments, replace textbooks or instructors, formally prove results, or certify mastery.
