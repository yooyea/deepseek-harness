# @deepseek-ai/dsh-client-ui-brand-deepharness

[English](README.md) | 中文

这是一个部署侧客户端插件，在不修改上游 UI 组件的情况下将 Web 应用壳展示为 **DeepHarness**。它通过现有 `settings.onboarding` 优先级机制覆盖带版本的内测声明和官方模型提供方引导，然后在上游浏览器界面之上投影 DeepHarness 字标、DH 缩写、文档标题、favicon 和 PWA 元数据。模型提供方和模型标识保持不变，因为它们属于功能 API 配置，并非产品品牌。

DOM 投影只识别上游字标的私有 clip-path id 和鱼形标识的精确 SVG view box。该副作用可逆，并通过限定范围的 `MutationObserver` 在 React 重新挂载后再次应用。

## Model Experience

无。该包只修改浏览器界面和新手引导组合，不修改提示词、工具、模型路由或模型提供方请求。

#### KV Cache effect

无；该包不组装任何模型请求内容。
