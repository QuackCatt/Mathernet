# Mathernet

[English](README.md) | [简体中文](README.zh-CN.md)

Mathernet is a local, AI-assisted formula learning workspace. Describe a formula in your own words, review the candidates, and add the right one to a visual knowledge map. You can also write study notes, review formulas, and explore the ideas behind them with AI.

Everything is managed in a web interface. After starting Mathernet once, you do not need to use command-line tools.

## What You Need

- A computer and a modern web browser.
- One AI API key from either **OpenRouter** or **DeepSeek**.
- No programming knowledge is required.

## Start Mathernet

If Mathernet is installed, open Terminal and enter:

```sh
mathernet start
```

If you downloaded and unzipped the project, open Terminal in that folder and enter:

```sh
./mathernet start
```

Keep the Terminal window open. Mathernet prints an address such as `http://127.0.0.1:8765`. Open that address in your browser. If the default port is already being used, Mathernet automatically chooses the next available port and prints the new address.

To stop Mathernet, close the Terminal window or press `Control + C` in Terminal.

## First-Time Setup

The AI provider settings open automatically the first time you use Mathernet.

1. Choose **OpenRouter** or **DeepSeek**.
2. Get an API key from the provider's official website.
3. Paste the API key into Mathernet.
4. Click **Save provider**.

Mathernet tests the connection automatically. When it is ready, the status light turns green and the settings window closes.

You only need to do this once. To change providers or keys later, click the **Settings** button in Mathernet.

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

You can continue asking questions in the conversation box at the bottom of **Explore deeper**.

### Work with the Map

- Drag formulas to arrange the map.
- Drag two formulas close together and release to create a relationship.
- Drag the red scissors onto a relationship line to remove it.
- Drag the blue magnifier onto a relationship line to explore why the formulas connect.
- Click an empty part of the map to return to the full map view.

The top-right buttons collapse the left and right panels when you want more space.

## Privacy

- Formula cards, notes, mind maps, generated conversations, and API settings stay on your computer.
- Personal learning data is stored in the local `data` folder.
- API keys are stored locally and are never uploaded to GitHub.
- When you use AI features, the relevant formula text and questions are sent to the AI provider you selected.

## Important

Mathernet is a study and organization tool. It does not solve graded assignments, replace textbooks or instructors, formally prove results, or certify mastery.
