'use client';

import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Boxes,
  Calculator,
  CircleAlert,
  Database,
  FlaskConical,
  Gauge,
  Info,
  Leaf,
  MapPinned,
  Route,
  ShieldAlert,
  Siren,
  SlidersHorizontal,
  Truck,
  Warehouse,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

type ReleaseStatus =
  | 'model_target'
  | 'model_minimum'
  | 'point_only_model'
  | 'baseline_fallback';

type City = {
  city_id: string;
  city_name_zh: string;
  province_name_zh: string;
  longitude: number;
  latitude: number;
  coordinate_method: string;
};

type Product = {
  vegetable_id: number;
  vegetable_code: string;
  vegetable_name_zh: string;
  data_file: string;
  record_count: number;
  city_count_by_horizon: Record<string, number>;
};

type Defaults = {
  vegetable_id: number;
  target_city_id: string;
  horizon_days: number;
  quantity_kg: number;
  transport_cost_per_kg_km: number;
  loss_rate: number;
  max_distance_km: number;
  road_factor: number;
  risk_aversion: number;
  minimum_reliability: number;
  reliability_gamma: number;
  maximum_reliability_multiplier: number;
};

type Metadata = {
  historical_scenario: boolean;
  data_as_of: string;
  scenario_origin_date: string;
  defaults: Defaults;
  horizons_days: number[];
  cities: City[];
  products: Product[];
  sensitivity_grid: {
    transport_cost_per_kg_km: number[];
    loss_rate: number[];
    risk_aversion: number[];
  };
  release_status_counts: Record<ReleaseStatus, number>;
};

type ProductPayload = {
  historical_scenario: boolean;
  scenario_origin_date: string;
  product: {
    vegetable_id: number;
    vegetable_code: string;
    vegetable_name_zh: string;
  };
  record_fields: string[];
  records: Array<Array<string | number | null>>;
};

type SourceRecord = {
  cityId: string;
  horizonDays: number;
  targetDate: string;
  releasedPoint: number;
  p10: number | null;
  p90: number | null;
  laterActualPrice: number;
  releaseStatus: ReleaseStatus;
  releasePointSource: string;
  priceInputLabel: string;
  intervalStatus: string;
  riskBasis: string;
  reliability: number;
  baseUncertainty: number;
  coverageRate: number;
  poorDayShare: number;
};

type Parameters = {
  quantityKg: number;
  transportRate: number;
  lossRate: number;
  maxDistanceKm: number;
  roadFactor: number;
  riskAversion: number;
  minimumReliability: number;
  reliabilityGamma: number;
  maximumReliabilityMultiplier: number;
};

type CostRow = SourceRecord & {
  city: City;
  straightLineDistanceKm: number;
  estimatedDistanceKm: number;
  transportCost: number;
  reliabilityMultiplier: number;
  riskPenalty: number;
  preLossCost: number;
  lossCost: number;
  unitLandedCost: number;
  totalLandedCost: number;
};

const statusPresentation: Record<ReleaseStatus, { label: string; className: string }> = {
  model_target: {
    label: '模型 + 合格区间',
    className: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-100',
  },
  model_minimum: {
    label: '模型 + 最低可用区间',
    className: 'bg-teal-100 text-teal-900 hover:bg-teal-100',
  },
  point_only_model: {
    label: '仅模型点预测',
    className: 'bg-amber-100 text-amber-950 hover:bg-amber-100',
  },
  baseline_fallback: {
    label: '基线回退',
    className: 'bg-slate-200 text-slate-900 hover:bg-slate-200',
  },
};

const priceFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });

function readRecords(payload: ProductPayload): SourceRecord[] {
  return payload.records.map((row) => ({
    cityId: String(row[0]),
    horizonDays: Number(row[1]),
    targetDate: String(row[2]),
    releasedPoint: Number(row[3]),
    p10: row[4] === null ? null : Number(row[4]),
    p90: row[5] === null ? null : Number(row[5]),
    laterActualPrice: Number(row[6]),
    releaseStatus: String(row[7]) as ReleaseStatus,
    releasePointSource: String(row[8]),
    priceInputLabel: String(row[9]),
    intervalStatus: String(row[10]),
    riskBasis: String(row[11]),
    reliability: Number(row[12]),
    baseUncertainty: Number(row[13]),
    coverageRate: Number(row[14]),
    poorDayShare: Number(row[15]),
  }));
}

function haversineKm(source: City, target: City) {
  const radius = 6371.0088;
  const radians = (value: number) => (value * Math.PI) / 180;
  const deltaLatitude = radians(target.latitude - source.latitude);
  const deltaLongitude = radians(target.longitude - source.longitude);
  const sourceLatitude = radians(source.latitude);
  const targetLatitude = radians(target.latitude);
  const value =
    Math.sin(deltaLatitude / 2) ** 2 +
    Math.cos(sourceLatitude) * Math.cos(targetLatitude) * Math.sin(deltaLongitude / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(Math.min(1, value)));
}

function calculateRows(
  records: SourceRecord[],
  cities: Map<string, City>,
  target: City,
  horizonDays: number,
  parameters: Parameters,
) {
  return records
    .filter((record) => record.horizonDays === horizonDays)
    .map((record): CostRow | null => {
      const city = cities.get(record.cityId);
      if (!city) return null;
      const straightLineDistanceKm = haversineKm(city, target);
      const estimatedDistanceKm = straightLineDistanceKm * parameters.roadFactor;
      const transportCost = estimatedDistanceKm * parameters.transportRate;
      const reliabilityMultiplier = Math.min(
        parameters.maximumReliabilityMultiplier,
        Math.max(1, 1 + parameters.reliabilityGamma * (1 - record.reliability)),
      );
      const riskPenalty =
        parameters.riskAversion * record.baseUncertainty * reliabilityMultiplier;
      const preLossCost = record.releasedPoint + transportCost + riskPenalty;
      const unitLandedCost = preLossCost / (1 - parameters.lossRate);
      return {
        ...record,
        city,
        straightLineDistanceKm,
        estimatedDistanceKm,
        transportCost,
        reliabilityMultiplier,
        riskPenalty,
        preLossCost,
        lossCost: unitLandedCost - preLossCost,
        unitLandedCost,
        totalLandedCost: unitLandedCost * parameters.quantityKg,
      };
    })
    .filter((row): row is CostRow => row !== null);
}

function rankExternal(rows: CostRow[], targetCityId: string, parameters: Parameters) {
  return rows
    .filter(
      (row) =>
        row.cityId !== targetCityId &&
        row.reliability >= parameters.minimumReliability &&
        row.estimatedDistanceKm <= parameters.maxDistanceKm,
    )
    .sort(
      (left, right) =>
        left.unitLandedCost - right.unitLandedCost ||
        right.reliability - left.reliability ||
        left.cityId.localeCompare(right.cityId),
    );
}

function numberInput(setter: (value: number) => void) {
  return (event: ChangeEvent<HTMLInputElement>) => setter(Number(event.target.value));
}

export default function ProcurementPage() {
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [vegetableId, setVegetableId] = useState<number | null>(null);
  const [targetCityId, setTargetCityId] = useState<string>('');
  const [horizonDays, setHorizonDays] = useState(28);
  const [quantityKg, setQuantityKg] = useState(10000);
  const [transportRate, setTransportRate] = useState(0.0025);
  const [lossPercent, setLossPercent] = useState(8);
  const [maxDistanceKm, setMaxDistanceKm] = useState(1500);
  const [riskAversion, setRiskAversion] = useState(0.5);
  const [minimumReliability, setMinimumReliability] = useState(0.65);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/procurement/metadata.json', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('metadata');
        return response.json() as Promise<Metadata>;
      })
      .then((data) => {
        setMetadata(data);
        setVegetableId(data.defaults.vegetable_id);
        setTargetCityId(data.defaults.target_city_id);
        setHorizonDays(data.defaults.horizon_days);
        setQuantityKg(data.defaults.quantity_kg);
        setTransportRate(data.defaults.transport_cost_per_kg_km);
        setLossPercent(data.defaults.loss_rate * 100);
        setMaxDistanceKm(data.defaults.max_distance_km);
        setRiskAversion(data.defaults.risk_aversion);
        setMinimumReliability(data.defaults.minimum_reliability);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('采购情景元数据没有载入。请先重新生成 P4 Web 数据。');
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!metadata || vegetableId === null) return;
    const product = metadata.products.find((item) => item.vegetable_id === vegetableId);
    if (!product) return;
    const controller = new AbortController();
    fetch(`/${product.data_file}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('product');
        return response.json() as Promise<ProductPayload>;
      })
      .then(setPayload)
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('当前产品的采购情景数据不可用，请更换产品或重建 P4 数据。');
        }
      });
    return () => controller.abort();
  }, [metadata, vegetableId]);

  const records = useMemo(() => (payload ? readRecords(payload) : []), [payload]);
  const cityMap = useMemo(
    () => new Map(metadata?.cities.map((city) => [city.city_id, city]) ?? []),
    [metadata],
  );
  const targetCity = cityMap.get(targetCityId) ?? null;
  const parameters = useMemo<Parameters | null>(
    () =>
      metadata
        ? {
            quantityKg,
            transportRate,
            lossRate: lossPercent / 100,
            maxDistanceKm,
            roadFactor: metadata.defaults.road_factor,
            riskAversion,
            minimumReliability,
            reliabilityGamma: metadata.defaults.reliability_gamma,
            maximumReliabilityMultiplier: metadata.defaults.maximum_reliability_multiplier,
          }
        : null,
    [
      lossPercent,
      maxDistanceKm,
      metadata,
      minimumReliability,
      quantityKg,
      riskAversion,
      transportRate,
    ],
  );
  const parameterError =
    quantityKg <= 0 ||
    transportRate < 0 ||
    lossPercent < 0 ||
    lossPercent >= 100 ||
    maxDistanceKm <= 0 ||
    riskAversion < 0 ||
    minimumReliability < 0 ||
    minimumReliability > 1;

  const evaluated = useMemo(() => {
    if (!targetCity || !parameters || parameterError) return [];
    return calculateRows(records, cityMap, targetCity, horizonDays, parameters);
  }, [cityMap, horizonDays, parameterError, parameters, records, targetCity]);
  const localBenchmark = evaluated.find((row) => row.cityId === targetCityId) ?? null;
  const candidates = parameters
    ? rankExternal(evaluated, targetCityId, parameters)
    : [];
  const topCandidates = candidates.slice(0, 3);
  const bestCandidate = topCandidates[0] ?? null;
  const savingsPerKg =
    bestCandidate && localBenchmark
      ? localBenchmark.unitLandedCost - bestCandidate.unitLandedCost
      : null;

  const sensitivity = useMemo(() => {
    if (!metadata || !targetCity || !parameters || parameterError) return [];
    const counts = new Map<
      string,
      { city: City; top3: number; first: number; minimumCost: number; maximumCost: number }
    >();
    let combinations = 0;
    for (const transport of metadata.sensitivity_grid.transport_cost_per_kg_km) {
      for (const loss of metadata.sensitivity_grid.loss_rate) {
        for (const risk of metadata.sensitivity_grid.risk_aversion) {
          combinations += 1;
          const scenarioParameters = {
            ...parameters,
            transportRate: transport,
            lossRate: loss,
            riskAversion: risk,
          };
          const rows = calculateRows(
            records,
            cityMap,
            targetCity,
            horizonDays,
            scenarioParameters,
          );
          const ranked = rankExternal(rows, targetCityId, scenarioParameters).slice(0, 3);
          ranked.forEach((row, index) => {
            const current = counts.get(row.cityId) ?? {
              city: row.city,
              top3: 0,
              first: 0,
              minimumCost: Number.POSITIVE_INFINITY,
              maximumCost: 0,
            };
            current.top3 += 1;
            if (index === 0) current.first += 1;
            current.minimumCost = Math.min(current.minimumCost, row.unitLandedCost);
            current.maximumCost = Math.max(current.maximumCost, row.unitLandedCost);
            counts.set(row.cityId, current);
          });
        }
      }
    }
    return [...counts.values()]
      .map((item) => ({
        ...item,
        top3Share: combinations ? item.top3 / combinations : 0,
        firstShare: combinations ? item.first / combinations : 0,
      }))
      .sort(
        (left, right) =>
          right.firstShare - left.firstShare ||
          right.top3Share - left.top3Share ||
          left.city.city_id.localeCompare(right.city.city_id),
      );
  }, [cityMap, horizonDays, metadata, parameterError, parameters, records, targetCity, targetCityId]);

  const currentProduct = metadata?.products.find((item) => item.vegetable_id === vegetableId);
  const selectedTargetDate = records.find((item) => item.horizonDays === horizonDays)?.targetDate;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/86 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Truck className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Vegetable Price Intelligence
              </p>
              <h1 className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
                Procurement Scenario Engine
              </h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Link href="/" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/75 px-3 font-medium transition-colors hover:bg-muted">
              <ArrowLeft className="size-3.5" aria-hidden="true" /> 历史监控
            </Link>
            <Link href="/forecast" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              <FlaskConical className="size-3.5" aria-hidden="true" /> 预测实验
            </Link>
            <Link href="/alerts" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              <Siren className="size-3.5" aria-hidden="true" /> 风险预警
            </Link>
            <Badge className="bg-amber-100 text-amber-950 hover:bg-amber-100">
              <Database data-icon="inline-start" /> Historical scenario
            </Badge>
            <span className="rounded-full border border-border bg-background/75 px-3 py-1.5 text-muted-foreground">
              数据截至 {metadata?.data_as_of ?? '2022-06-22'}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section className="mb-5" aria-labelledby="procurement-controls">
          <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                P4 · 空间价差 → 风险调整成本 → Pricing 输入
              </p>
              <h2 id="procurement-controls" className="font-heading text-2xl font-semibold tracking-tight">
                把城市价差转化为可复核的到岸成本
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                系统严格沿用 P2 已发布的模型或基线价格，再加入空间摩擦、损耗与不确定性，给出值得询价的候选来源和 Pricing 成本输入。
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline" className="bg-card/80">117 个城市锚点</Badge>
              <Badge variant="outline" className="bg-card/80">36 组敏感性</Badge>
              <Badge variant="outline" className="bg-card/80">情景起点 2022.05.01</Badge>
            </div>
          </div>

          <Alert className="mb-4 border-primary/25 bg-primary/6">
            <CircleAlert />
            <AlertTitle>Pricing Decision Bridge · 成本与毛利复核输入</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>
                结果可用于更新成本基准、触发毛利与报价复核、准备替代来源询价；pricing engine 再结合库存、客户、利润和审批规则决定价格。
              </p>
              <div className="flex flex-wrap gap-1.5 text-[11px] font-medium text-primary">
                <span className="rounded-md border border-primary/15 bg-background/70 px-2 py-1">成本基准</span>
                <span className="rounded-md border border-primary/15 bg-background/70 px-2 py-1">毛利复核</span>
                <span className="rounded-md border border-primary/15 bg-background/70 px-2 py-1">供应替代询价</span>
              </div>
              <p className="text-amber-900">
                历史参数化情景，不执行采购，也不生成零售价。距离是城市中心估算，没有实时运费、道路路线、库存或供应能力。
              </p>
            </AlertDescription>
          </Alert>

          <Card className="border-0 bg-[linear-gradient(115deg,var(--card),color-mix(in_oklab,var(--accent)_55%,var(--card)))] py-3 shadow-[0_14px_44px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
            <CardContent className="grid gap-3 px-3 sm:grid-cols-2 sm:px-4 lg:grid-cols-3">
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                目标城市
                <NativeSelect className="w-full" value={targetCityId} onChange={(event) => setTargetCityId(event.target.value)}>
                  {metadata?.cities.map((city) => (
                    <NativeSelectOption key={city.city_id} value={city.city_id}>
                      {city.city_name_zh} · {city.province_name_zh}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                核心蔬菜
                <NativeSelect
                  className="w-full"
                  value={vegetableId ?? ''}
                  onChange={(event) => {
                    setPayload(null);
                    setError(null);
                    setVegetableId(Number(event.target.value));
                  }}
                >
                  {metadata?.products.map((product) => (
                    <NativeSelectOption key={product.vegetable_id} value={product.vegetable_id}>
                      {product.vegetable_name_zh} · {product.vegetable_code}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                采购规划跨度
                <NativeSelect className="w-full" value={horizonDays} onChange={(event) => setHorizonDays(Number(event.target.value))}>
                  {metadata?.horizons_days.map((days) => (
                    <NativeSelectOption key={days} value={days}>
                      {days} 日{days === 28 ? ' · 默认中期规划' : days === 14 ? ' · 战术采购' : ' · 近期补货'}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
            </CardContent>
          </Card>
        </section>

        {error ? (
          <Alert variant="destructive" className="bg-card py-4">
            <CircleAlert />
            <AlertTitle>采购情景数据不可用</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : !metadata || !payload ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-28 rounded-xl" />)}
            </div>
            <Skeleton className="h-[420px] rounded-xl" />
          </div>
        ) : (
          <div className="space-y-5">
            {parameterError && (
              <Alert variant="destructive" className="bg-card">
                <CircleAlert />
                <AlertTitle>参数范围无效</AlertTitle>
                <AlertDescription>采购量和最大距离必须大于零；损耗率需低于100%；风险偏好、运费和可靠性阈值不能为负。</AlertDescription>
              </Alert>
            )}

            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="采购情景摘要">
              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader><CardDescription>最佳外地候选</CardDescription><CardTitle className="text-xl">{bestCandidate?.city.city_name_zh ?? '暂无候选'}</CardTitle></CardHeader>
                <CardContent className="text-xs leading-5 text-muted-foreground">{bestCandidate ? `${bestCandidate.city.province_name_zh} · ${integerFormatter.format(bestCandidate.estimatedDistanceKm)} 公里估算运输距离` : '调整最大距离或可靠性门槛'}</CardContent>
              </Card>
              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader><CardDescription>最佳单位到岸成本</CardDescription><CardTitle className="text-xl tabular-nums">{bestCandidate ? `¥${priceFormatter.format(bestCandidate.unitLandedCost)}/kg` : '—'}</CardTitle></CardHeader>
                <CardContent className="text-xs leading-5 text-muted-foreground">价格、运输、风险和损耗使用同一公斤口径</CardContent>
              </Card>
              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader><CardDescription>本地基准</CardDescription><CardTitle className="text-xl tabular-nums">{localBenchmark ? `¥${priceFormatter.format(localBenchmark.unitLandedCost)}/kg` : '无合格本地报价'}</CardTitle></CardHeader>
                <CardContent className="text-xs leading-5 text-muted-foreground">{localBenchmark ? localBenchmark.priceInputLabel : '仍可比较外地候选，但不计算模拟节省'}</CardContent>
              </Card>
              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader><CardDescription>相对本地模拟节省</CardDescription><CardTitle className={`text-xl tabular-nums ${savingsPerKg !== null && savingsPerKg > 0 ? 'text-emerald-700' : ''}`}>{savingsPerKg === null ? '—' : `${savingsPerKg >= 0 ? '+' : ''}¥${priceFormatter.format(savingsPerKg)}/kg`}</CardTitle></CardHeader>
                <CardContent className="text-xs leading-5 text-muted-foreground">参数化比较，不是已经实现的采购收益</CardContent>
              </Card>
            </section>

            <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
              <CardHeader className="border-b border-border/70">
                <CardTitle className="flex items-center gap-2"><SlidersHorizontal className="size-4 text-primary" /> 情景参数</CardTitle>
                <CardDescription>编辑输入后，成本、排名和比较静态结果会即时重算。道路折算系数固定为 {metadata.defaults.road_factor.toFixed(2)}。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 pt-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                <label htmlFor="quantity-kg" className="grid gap-1.5 text-xs font-medium text-muted-foreground">到货可用量（kg）<Input id="quantity-kg" type="number" min="1" step="100" value={quantityKg} onChange={numberInput(setQuantityKg)} /></label>
                <label htmlFor="transport-rate" className="grid gap-1.5 text-xs font-medium text-muted-foreground">运输费率 · 空间摩擦<Input id="transport-rate" type="number" min="0" step="0.0001" value={transportRate} onChange={numberInput(setTransportRate)} /></label>
                <label htmlFor="loss-percent" className="grid gap-1.5 text-xs font-medium text-muted-foreground">损耗率 · Cost-to-serve（%）<Input id="loss-percent" type="number" min="0" max="99" step="1" value={lossPercent} onChange={numberInput(setLossPercent)} /></label>
                <label htmlFor="max-distance" className="grid gap-1.5 text-xs font-medium text-muted-foreground">最大运输距离（km）<Input id="max-distance" type="number" min="1" step="50" value={maxDistanceKm} onChange={numberInput(setMaxDistanceKm)} /></label>
                <label htmlFor="risk-aversion" className="grid gap-1.5 text-xs font-medium text-muted-foreground">风险偏好 λ · 风险厌恶<Input id="risk-aversion" type="number" min="0" max="1.5" step="0.1" value={riskAversion} onChange={numberInput(setRiskAversion)} /></label>
                <label htmlFor="minimum-reliability" className="grid gap-1.5 text-xs font-medium text-muted-foreground">最低可靠性<Input id="minimum-reliability" type="number" min="0" max="1" step="0.05" value={minimumReliability} onChange={numberInput(setMinimumReliability)} /></label>
              </CardContent>
            </Card>

            <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
              <CardHeader className="border-b border-border/70">
                <CardTitle className="flex items-center gap-2"><Warehouse className="size-4 text-primary" /> Top 3 外地候选</CardTitle>
                <CardDescription>{currentProduct?.vegetable_name_zh} · {targetCity?.city_name_zh} · {horizonDays} 日 · 目标日期 {selectedTargetDate ?? '—'}。候选先经过可靠性与距离门槛。</CardDescription>
              </CardHeader>
              <CardContent className="px-0">
                {topCandidates.length === 0 ? (
                  <Empty className="py-12">
                    <EmptyHeader><EmptyMedia variant="icon"><Route /></EmptyMedia><EmptyTitle>当前参数下没有合格外地候选</EmptyTitle><EmptyDescription>扩大最大距离或降低可靠性门槛后重试。系统不会用零成本填补空结果。</EmptyDescription></EmptyHeader>
                  </Empty>
                ) : (
                  <Table>
                    <TableHeader><TableRow className="bg-muted/45"><TableHead>排名与来源</TableHead><TableHead>发布价格</TableHead><TableHead>风险缓冲</TableHead><TableHead>估算距离</TableHead><TableHead>运输</TableHead><TableHead>损耗</TableHead><TableHead>单位到岸</TableHead><TableHead>总成本</TableHead><TableHead>相对本地</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {topCandidates.map((row, index) => {
                        const status = statusPresentation[row.releaseStatus];
                        const saving = localBenchmark ? localBenchmark.unitLandedCost - row.unitLandedCost : null;
                        return (
                          <TableRow key={row.cityId}>
                            <TableCell><div className="flex items-start gap-2"><span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/9 font-heading font-semibold text-primary">{index + 1}</span><div><div className="font-medium">{row.city.city_name_zh}</div><div className="text-xs text-muted-foreground">{row.city.province_name_zh} · 可靠性 {(row.reliability * 100).toFixed(1)}%</div></div></div></TableCell>
                            <TableCell><div className="font-mono font-semibold">¥{priceFormatter.format(row.releasedPoint)}</div><Badge className={`mt-1 ${status.className}`}>{status.label}</Badge><div className="mt-1 max-w-52 whitespace-normal text-[11px] leading-4 text-muted-foreground">{row.priceInputLabel}</div></TableCell>
                            <TableCell><div className="font-mono">¥{priceFormatter.format(row.riskPenalty)}</div><div className="text-[11px] text-muted-foreground">{row.intervalStatus === 'calibrated_released' ? 'P90−点预测' : '历史发布残差 Q80'}</div></TableCell>
                            <TableCell className="font-mono">{integerFormatter.format(row.estimatedDistanceKm)} km</TableCell>
                            <TableCell className="font-mono">¥{priceFormatter.format(row.transportCost)}</TableCell>
                            <TableCell className="font-mono">¥{priceFormatter.format(row.lossCost)}</TableCell>
                            <TableCell className="font-mono font-semibold">¥{priceFormatter.format(row.unitLandedCost)}</TableCell>
                            <TableCell className="font-mono">¥{integerFormatter.format(row.totalLandedCost)}</TableCell>
                            <TableCell className={`font-mono ${saving !== null && saving > 0 ? 'text-emerald-700' : 'text-muted-foreground'}`}>{saving === null ? '无本地基准' : `${saving >= 0 ? '+' : ''}¥${priceFormatter.format(saving)}/kg`}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/70">
                  <CardTitle className="flex items-center gap-2"><Gauge className="size-4 text-primary" /> 比较静态 · 36 组参数下的排名稳定性</CardTitle>
                  <CardDescription>固定当前城市、产品、跨度、距离和可靠性门槛，观察空间摩擦、损耗和风险厌恶变化如何改变候选选择。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 pt-1">
                  {sensitivity.slice(0, 5).map((item) => (
                    <div key={item.city.city_id} className="rounded-lg border border-border/70 bg-background/55 p-3">
                      <div className="mb-2 flex items-center justify-between gap-3"><div><div className="font-medium">{item.city.city_name_zh}</div><div className="text-xs text-muted-foreground">成本范围 ¥{priceFormatter.format(item.minimumCost)}–¥{priceFormatter.format(item.maximumCost)}/kg</div></div><Badge variant="outline">第一名 {(item.firstShare * 100).toFixed(0)}%</Badge></div>
                      <div aria-label={`进入 Top 3 的比例 ${(item.top3Share * 100).toFixed(0)}%`}>
                        <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                          <span>进入 Top 3</span>
                          <span className="font-mono">{(item.top3Share * 100).toFixed(0)}%</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-[width]"
                            style={{ width: `${item.top3Share * 100}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card className="border-0 bg-card/94 shadow-sm ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2"><Calculator className="size-4 text-primary" /> 公式与证据边界</CardTitle><CardDescription>排名为什么会变化，以及它没有覆盖什么。</CardDescription></CardHeader>
                <CardContent className="space-y-4 pt-1 text-sm leading-6 text-muted-foreground">
                  <div className="rounded-lg bg-primary/6 p-3 font-mono text-xs text-foreground">单位到岸 =（发布点价格 + 运输 + 风险）÷（1 − 损耗率）</div>
                  <ul className="space-y-2">
                    <li className="flex gap-2"><MapPinned className="mt-1 size-4 shrink-0 text-primary" />城市中心直线距离 × {metadata.defaults.road_factor.toFixed(2)}，不是公路路线或运输时效。</li>
                    <li className="flex gap-2"><ShieldAlert className="mt-1 size-4 shrink-0 text-primary" />只有4/30个产品×跨度组发布区间；其余风险项来自无前视历史发布残差。</li>
                    <li className="flex gap-2"><Boxes className="mt-1 size-4 shrink-0 text-primary" />没有库存、产能、规格、供应承诺或真实成交量，候选仍需人工询价。</li>
                  </ul>
                  <Alert className="border-border bg-muted/45"><Info /><AlertTitle>基线价格保持可见</AlertTitle><AlertDescription>7日回退显示“当前价格延续（基线），不是模型预测”；28日黄瓜等显示“历史季节中位数（基线），不是模型预测”。</AlertDescription></Alert>
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        <footer className="mt-6 flex flex-col gap-2 border-t border-border/70 py-5 text-xs leading-5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-1.5"><Leaf className="size-3.5 text-primary" />P4 scenario_release 只表示历史参数化情景可演示。</span>
          <span className="flex items-center gap-1.5"><Truck className="size-3.5 text-primary" />不接供应商、不下单、不自动调价。</span>
        </footer>
      </div>
    </main>
  );
}
