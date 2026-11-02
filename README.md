# 新词雷达：免费来源日报

使用 [new-term-radar](https://github.com/zhuyansen/new-term-radar) 的免费采集器，保留上游 MIT 许可证；上游代码取自 3cf6515c4076cb2800819473062d9b36d563d0fe。每天北京时间 08:00 执行，公开 `public/latest.json`。采集仅针对公开来源，不调用 AIsa、GoAnyAPI、TrustMRR 等付费接口。来源错误和首次建立快照会在报告中标记。

GitHub Actions 缓存保存来源快照；缓存被清理后，部分来源需要重新建立基线。报告内容公开可访问，不应放入私有信息或密钥。
