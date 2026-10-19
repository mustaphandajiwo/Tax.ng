import { useEffect, type ReactNode } from "react";
import { api, type Meta } from "./api";
import { Layout } from "./components/Layout";
import { Loading, useLoad } from "./components/ui";
import { CalculatorIndex, CitCalculator, CompareCalculator, PitCalculator, VatCalculator, WhtCalculator } from "./pages/calculators";
import { About, GuidePage, Home, LawPage, Laws, News, NotFound, Reform } from "./pages/content";
import { Ask, Newsletter } from "./pages/interactive";
import { match, useRoute } from "./router";

type Render = (params: Record<string, string>, meta: Meta) => ReactNode;

// Phase 1 routes only (PRD section 5). Later-phase pages are added with their phase.
const ROUTES: [string, Render][] = [
  ["/", () => <Home />],
  ["/reform", () => <Reform />],
  ["/reform/:id", (p) => <GuidePage id={p.id} />],
  ["/calculators", () => <CalculatorIndex />],
  ["/calculators/pit", (_, meta) => <PitCalculator meta={meta} />],
  ["/calculators/pit-compare", () => <CompareCalculator />],
  ["/calculators/cit", () => <CitCalculator />],
  ["/calculators/vat", (_, meta) => <VatCalculator meta={meta} />],
  ["/calculators/wht", (_, meta) => <WhtCalculator meta={meta} />],
  ["/laws", () => <Laws />],
  ["/laws/:id", (p) => <LawPage id={p.id} />],
  ["/news", () => <News />],
  ["/ask", () => <Ask />],
  ["/newsletter", (_, meta) => <Newsletter meta={meta} />],
  ["/about", () => <About />],
];

function render(path: string, meta: Meta): ReactNode {
  for (const [pattern, view] of ROUTES) {
    const params = match(pattern, path);
    if (params) return view(params, meta);
  }
  return <NotFound />;
}

export function App() {
  const path = useRoute();
  const { data: meta, error } = useLoad(() => api.meta(), []);

  useEffect(() => {
    void api.event("page_view", { page: path.split("/").slice(0, 2).join("/") || "/" });
  }, [path]);

  return (
    <Layout meta={meta} path={path}>
      {meta ? render(path, meta) : <Loading error={error} />}
    </Layout>
  );
}
