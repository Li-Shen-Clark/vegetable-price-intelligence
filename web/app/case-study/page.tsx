import type { Metadata } from 'next';
import Link from 'next/link';
import {
  ArrowRight,
  BarChart3,
  BriefcaseBusiness,
  CheckCircle2,
  CircleAlert,
  Database,
  FlaskConical,
  Gauge,
  Leaf,
  LineChart,
  Network,
  Scale,
  ShieldCheck,
  Siren,
  Truck,
  Waves,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export const metadata: Metadata = {
  title: 'Case Study | Vegetable Price Intelligence',
  description:
    'A data-free portfolio case study connecting market measurement, forecasting, risk, procurement economics, and model-release governance to pricing decisions.',
  openGraph: {
    title: 'Vegetable Price Intelligence',
    description: 'From market signals to governed pricing decisions.',
    images: [{ url: '/og.png', width: 3072, height: 1728, alt: 'Vegetable Price Intelligence portfolio cover' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Vegetable Price Intelligence',
    description: 'From market signals to governed pricing decisions.',
    images: ['/og.png'],
  },
};

const stages = [
  {
    step: 'P0',
    title: '可信市场事实',
    question: '这条价格能比较吗？',
    evidence: '868 万市场报价 → 735 万城市日事实',
    status: 'data release',
    icon: Database,
  },
  {
    step: 'P1',
    title: '历史市场基准',
    question: '相对城市与季节处于哪里？',
    evidence: '30 种蔬菜的趋势、排名与质量',
    status: 'historical',
    icon: LineChart,
  },
  {
    step: 'P2',
    title: '价格预期',
    question: '模型是否胜过简单规则？',
    evidence: '总体 WAPE 改善 6.30%，弱切片回退',
    status: 'partial release',
    icon: FlaskConical,
  },
  {
    step: 'P3',
    title: '涨价风险复核',
    question: '固定误报预算下是否值得检查？',
    evidence: 'Recall 37.69% @ FPR 9.99%',
    status: 'alert release',
    icon: Siren,
  },
  {
    step: 'P4',
    title: '采购成本情景',
    question: '低价能否覆盖摩擦与风险？',
    evidence: '36 组运输、损耗与风险敏感性',
    status: 'scenario release',
    icon: Truck,
  },
  {
    step: 'P5',
    title: '共同冲击治理',
    question: '方向关系能否跨窗口复现？',
    evidence: '15 条冻结边仅 4 条 final 改善为正',
    status: 'network no-go',
    icon: Waves,
  },
];

const routeLinks = [
  { href: '/', label: 'Historical Monitor', note: '历史基准', icon: LineChart },
  { href: '/forecast', label: 'Forecast Lab', note: '部分发布', icon: FlaskConical },
  { href: '/alerts', label: 'Risk Alert', note: '人工复核', icon: Siren },
  { href: '/procurement', label: 'Procurement', note: '成本情景', icon: Truck },
  { href: '/propagation', label: 'Common Shock', note: '方向 no-go', icon: Waves },
];

export default function CaseStudyPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/88 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <BriefcaseBusiness className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">Portfolio Case Study</p>
              <p className="font-heading text-lg font-semibold tracking-tight">Vegetable Price Intelligence</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge className="bg-emerald-100 text-emerald-950 hover:bg-emerald-100"><ShieldCheck data-icon="inline-start" /> Data-free view</Badge>
            <Badge variant="outline" className="bg-card/85"><Database data-icon="inline-start" /> Source data stays local</Badge>
            <Link href="/" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              Open analytical workspace <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-9">
        <section className="grid gap-6 border-b border-border/65 pb-8 lg:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)] lg:items-end">
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-primary">Economics-informed pricing decision support</p>
            <h1 className="max-w-4xl font-heading text-4xl font-semibold leading-[1.08] tracking-[-0.035em] sm:text-5xl lg:text-6xl">
              从市场信号到可治理的 Pricing 决策
            </h1>
            <p className="mt-5 max-w-3xl text-base leading-7 text-muted-foreground sm:text-lg sm:leading-8">
              我把九年批发价格构建成一套 Pricing Intelligence layer：先证明数据能比较，再形成价格预期、风险复核和成本情景；证据不足时回退或 no-go，而不是输出未经验证的价格动作。
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <a href="#decision-chain" className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-sm transition-opacity hover:opacity-90">查看决策链 <ArrowRight className="size-4" /></a>
              <a href="#evidence" className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-card px-4 text-sm font-semibold transition-colors hover:bg-muted">查看正式证据</a>
            </div>
          </div>
          <Alert className="border-amber-300/70 bg-amber-50 text-amber-950">
            <CircleAlert />
            <AlertTitle>它不是实时 Pricing Engine</AlertTitle>
            <AlertDescription className="space-y-2 leading-6">
              <p>本项目提供历史市场、预测、风险和成本证据；最终价格仍需当前成本、库存、客户、合同、利润与审批规则。</p>
              <p className="font-medium">数据截至 2022-06-22；不估计需求弹性、最优零售价、真实采购收益或因果传播。</p>
            </AlertDescription>
          </Alert>
        </section>

        <section className="grid gap-3 py-6 sm:grid-cols-2 lg:grid-cols-4" aria-label="项目规模">
          {[
            ['8.68M', '市场报价', '保留原始审计键与无效记录'],
            ['117', '城市', '城市日两级中位价格'],
            ['30', '蔬菜', '10 种进入正式建模范围'],
            ['177', '本地自动测试', '数据、泄漏、指标与发布契约'],
          ].map(([value, label, note]) => (
            <Card key={label} className="border-0 bg-card/92 ring-1 ring-foreground/8">
              <CardContent className="pt-4">
                <p className="font-heading text-3xl font-semibold tabular-nums text-primary">{value}</p>
                <p className="mt-1 text-sm font-semibold">{label}</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{note}</p>
              </CardContent>
            </Card>
          ))}
        </section>

        <section id="decision-chain" className="py-7" aria-labelledby="decision-chain-title">
          <div className="mb-5 max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">One system · six governed stages</p>
            <h2 id="decision-chain-title" className="mt-1 font-heading text-2xl font-semibold tracking-tight sm:text-3xl">每一层先回答决策问题，再选择模型</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">发布状态是产品功能的一部分：成功、部分发布、情景、人工复核和 no-go 都必须保留原始含义。</p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {stages.map((stage) => {
              const Icon = stage.icon;
              return (
                <Card key={stage.step} className="border-0 bg-card/94 shadow-[0_12px_36px_rgb(43_66_54/5%)] ring-1 ring-foreground/8">
                  <CardHeader className="grid-cols-[auto_1fr] items-start gap-3">
                    <span className="flex size-10 items-center justify-center rounded-xl bg-primary/8 text-primary"><Icon className="size-5" /></span>
                    <div><CardDescription className="font-mono text-[11px] font-semibold text-primary">{stage.step} · {stage.status}</CardDescription><CardTitle className="mt-1 text-base">{stage.title}</CardTitle></div>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm">
                    <p className="font-medium">{stage.question}</p>
                    <p className="leading-6 text-muted-foreground">{stage.evidence}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>

        <section id="evidence" className="grid gap-4 border-y border-border/65 py-8 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Evidence before sophistication</p>
            <h2 className="mt-1 font-heading text-2xl font-semibold tracking-tight sm:text-3xl">最有价值的结果，是知道何时不发布</h2>
            <p className="mt-3 max-w-xl text-sm leading-7 text-muted-foreground">统计显著、漂亮可视化或平均改善都不自动成为产品功能。每一层必须相对强基线、错误成本和预设 release gate 获得资格。</p>
            <div className="mt-5 rounded-xl bg-primary p-5 text-primary-foreground">
              <Network className="size-5 opacity-80" />
              <p className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] opacity-75">P5 sealed final test</p>
              <p className="mt-1 font-heading text-3xl font-semibold">15 → 4 → 0</p>
              <p className="mt-2 text-sm leading-6 opacity-85">15 条 validation/稳定性边中仅 4 条 final 改善为正；跨产品网络发布边为 0，产品降级为共同冲击与城市暴露。</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              { title: '强基线', text: 'P2 与 last price、weekly pattern 和 seasonal median 比较；10 个弱产品×跨度组继续使用基线。', icon: Scale },
              { title: '错误成本', text: 'P3 在 FPR≤10% 下冻结阈值，并公开 precision 21.31%，只进入人工复核。', icon: Gauge },
              { title: '参数敏感性', text: 'P4 用 36 组运输、损耗和风险偏好区分“最低成本”与“排名稳定”。', icon: BarChart3 },
              { title: '竞争解释', text: 'P5 先剔除共同冲击；训练期同时相关 FDR 关系减少 47.60%。', icon: Waves },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <Card key={item.title} className="border-0 bg-muted/68 ring-1 ring-foreground/7">
                  <CardContent className="pt-4"><Icon className="size-5 text-primary" /><p className="mt-3 font-semibold">{item.title}</p><p className="mt-1 text-sm leading-6 text-muted-foreground">{item.text}</p></CardContent>
                </Card>
              );
            })}
          </div>
        </section>

        <section className="grid gap-5 py-8 lg:grid-cols-[1.1fr_0.9fr]">
          <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
            <CardHeader><CardDescription className="font-semibold uppercase tracking-[0.12em] text-primary">Economics → product behavior</CardDescription><CardTitle>经济学不只存在于背景介绍</CardTitle></CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              {[
                ['价格离散', '先控制市场构成与覆盖，再比较城市相对价格。'],
                ['预期与不确定性', '预测必须相对当时可知基线，并分别决定点和区间是否发布。'],
                ['交易成本', '低裸价只有覆盖运输、损耗和风险后才值得询价。'],
                ['共同冲击', '全国同步变化是城市传播的竞争解释，不可自动解释为因果。'],
              ].map(([title, text]) => <div key={title} className="rounded-lg border border-border/70 p-3"><p className="text-sm font-semibold">{title}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{text}</p></div>)}
            </CardContent>
          </Card>
          <Card className="border-0 bg-[linear-gradient(145deg,color-mix(in_oklab,var(--primary)_8%,var(--card)),var(--card))] ring-1 ring-foreground/8">
            <CardHeader><CardDescription className="font-semibold uppercase tracking-[0.12em] text-primary">Pricing interface</CardDescription><CardTitle>交付证据，不越过审批</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6">
              {['成本基准与来源可靠性', '模型 / 基线 / no-go 发布状态', '涨价风险与人工复核时点', '风险调整到岸成本和敏感性', '共同冲击与城市暴露范围'].map((item) => <p key={item} className="flex gap-2"><CheckCircle2 className="mt-1 size-4 shrink-0 text-primary" /> <span>{item}</span></p>)}
              <p className="border-t border-border/70 pt-3 text-muted-foreground">Pricing engine 再结合库存、客户、合同、margin floor 与审批规则决定最终价格。</p>
            </CardContent>
          </Card>
        </section>

        <section className="pb-8" aria-labelledby="workspace-title">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Local analytical workspace</p><h2 id="workspace-title" className="mt-1 font-heading text-2xl font-semibold tracking-tight">查看五个历史工作台</h2></div>
            <Badge variant="outline" className="w-fit bg-card/80">需要本地授权数据</Badge>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {routeLinks.map((item) => {
              const Icon = item.icon;
              return <Link key={item.href} href={item.href} className="group rounded-xl border border-border bg-card/85 p-3 transition-colors hover:border-primary/30 hover:bg-primary/5"><Icon className="size-4 text-primary" /><p className="mt-3 text-sm font-semibold group-hover:text-primary">{item.label}</p><p className="mt-0.5 text-xs text-muted-foreground">{item.note}</p></Link>;
            })}
          </div>
        </section>

        <footer className="flex flex-col gap-2 border-t border-border/60 py-5 text-xs leading-5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>Historical portfolio · source period 2014-02-02—2022-06-22</span>
          <span className="flex items-center gap-1.5"><Leaf className="size-3.5" /> Data, artifacts and execution logs are not published.</span>
        </footer>
      </div>
    </main>
  );
}
