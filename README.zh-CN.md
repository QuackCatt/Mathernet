# Mathernet

[English](README.md) | [简体中文](README.zh-CN.md)

Mathernet 是一个在电脑本地运行的 AI 公式学习工具。你可以用普通文字描述一个公式，查看 AI 找到的候选公式，把正确的公式加入可视化知识地图，也可以记录学习笔记、标记学习状态，并通过 AI 深入了解公式背后的故事、背景和应用。

启动 Mathernet 后，所有操作都在网页中完成，不需要再使用命令行。

## 你需要准备

- 一台电脑和一个现代浏览器。
- **OpenRouter** 或 **DeepSeek** 任意一家的 API Key。
- 不需要任何编程知识。

## 启动 Mathernet

如果你已经安装 Mathernet，请打开“终端”，输入：

```sh
mathernet start
```

如果你下载的是 GitHub 压缩包，请先解压，然后在该文件夹中打开“终端”，输入：

```sh
./mathernet start
```

请保持“终端”窗口不要关闭。Mathernet 会显示类似 `http://127.0.0.1:8765` 的地址，把这个地址复制到浏览器中打开即可。

如果默认端口已经被其他程序占用，Mathernet 会自动尝试下一个端口，并显示新的访问地址。

需要停止 Mathernet 时，关闭“终端”窗口，或者在“终端”中按 `Control + C`。

## 首次使用

第一次进入 Mathernet 时，AI 服务设置会自动弹出。

1. 选择 **OpenRouter** 或 **DeepSeek**。
2. 到对应官网获取 API Key。
3. 把 API Key 粘贴到 Mathernet。
4. 点击 **Save provider**。

Mathernet 会自动测试连接。连接成功后，状态灯会变成绿色，设置窗口随后关闭。

这个步骤只需要完成一次。以后需要更换服务或 API Key 时，点击 Mathernet 中的 **Settings** 即可。

## 获取 API Key

### OpenRouter

1. 打开 [OpenRouter API Keys 官方页面](https://openrouter.ai/keys)。
2. 登录，或者注册一个 OpenRouter 账号。
3. 点击 **Create Key**，名称可以简单填写为 `Mathernet`，然后创建。
4. 立即复制完整的 API Key。OpenRouter 可能不会再次显示完整内容。
5. 在 Mathernet 中选择 **OpenRouter**，粘贴 API Key，点击 **Save provider**。

如果不知道应该选择哪个模型，保留程序推荐的模型即可。你也可以点击 **Load models**，查看你的 OpenRouter 账号可用的模型。

### DeepSeek

1. 打开 [DeepSeek API Keys 官方页面](https://platform.deepseek.com/api_keys)。
2. 登录，或者注册一个 DeepSeek 账号。
3. 创建一个新的 API Key。
4. 复制完整的 API Key。
5. 在 Mathernet 中选择 **DeepSeek**，粘贴 API Key，点击 **Save provider**。

DeepSeek 不需要手动填写模型名称，Mathernet 会自动使用 DeepSeek 的标准对话模型。

API Key 只保存在你的电脑上，保存后程序不会再次显示完整内容。

## 使用 Mathernet

### 创建思维导图

点击 **New mind map**，输入名称并确认。每个思维导图都是独立空间，可以按课程或主题分别整理。

### 添加公式

1. 在顶部搜索框输入公式、公式名称或者一段普通描述。
2. 等待 Mathernet 显示最多五个候选公式。
3. 点击最符合需要的公式。

Mathernet 会先搜索现有公式库。如果这个公式已经存在，就会直接打开已有卡片，不会重复创建。

### 阅读公式

点击一个公式后，右侧会显示详细内容：

- **Overview**：公式本身和简短介绍。
- **Explore deeper**：更深入的背景、故事和应用；能够找到可靠来源时，还会在文章末尾提供链接。
- **Learning**：学习状态、个人学习笔记。

在 **Explore deeper** 页面底部，还可以继续向 AI 提问。

### 操作知识地图

- 拖动公式圆点来整理地图。
- 把两个公式拖得很近并松开，即可创建它们之间的关系。
- 把红色剪刀拖到关系线上，可以解除关系。
- 把蓝色放大镜拖到关系线上，可以探索两个公式为什么存在联系。
- 点击地图空白位置，可以返回完整地图。

右上角的两个按钮可以分别收起左右侧栏，为地图留出更多空间。

## 隐私说明

- 公式卡片、笔记、思维导图、生成的对话和 AI 设置都保存在你的电脑上。
- 个人学习数据保存在本地 `data` 文件夹中。
- API Key 只保存在本地，不会上传到 GitHub。
- 使用 AI 功能时，相关的公式内容和你的问题会发送给你选择的 AI 服务。

## 重要说明

Mathernet 是学习和整理工具。它不会替你完成计分作业，也不会代替教材、老师、正式证明或学习能力认证。
