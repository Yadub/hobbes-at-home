import type { ReactNode } from "react";
import { ToastHost } from "./components/Controls";
import { ChecklistIcon, ForkKnifeIcon, GearIcon, HeartIcon, HouseIcon } from "./components/Icons";
import { Page } from "./components/Page";
import { AssistantHome } from "./pages/assistant/Home";
import { ProfilePage } from "./pages/assistant/ProfilePage";
import { SessionsPage } from "./pages/assistant/Sessions";
import { TaskPage } from "./pages/assistant/TaskPage";
import { DrinksPage } from "./pages/diet/DrinksPage";
import { Goals } from "./pages/diet/Goals";
import { HistoryPage } from "./pages/diet/History";
import { MealPage } from "./pages/diet/MealPage";
import { Today } from "./pages/diet/Today";
import { HealthSetup } from "./pages/HealthSetup";
import { WhoopSetup } from "./pages/WhoopSetup";
import { RegionPage } from "./pages/RegionPage";
import { Settings } from "./pages/Settings";
import { HealthPage } from "./pages/health/HealthPage";
import { MetricPage } from "./pages/health/MetricPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { BackupsPage } from "./pages/BackupsPage";
import { Summary } from "./pages/Summary";
import { hardReload, useUpdateAvailable } from "./lib/updates";
import { Link, match, usePath } from "./router";

type Tab = { path: string; label: string; icon: (filled: boolean) => ReactNode };

// Every section is in the sidebar (laptop) and the tab bar (phone). Settings is the gear on Summary.
const SECTIONS: Tab[] = [
  { path: "/", label: "Summary", icon: (f) => <HouseIcon filled={f} /> },
  { path: "/health", label: "Health", icon: () => <HeartIcon /> },
  { path: "/diet", label: "Diet", icon: () => <ForkKnifeIcon /> },
  { path: "/assistant", label: "Hobbes AI", icon: () => <ChecklistIcon /> },
];
// On a phone, Settings counts as Summary's (its gear).
const TAB_OF: Record<string, string> = { "/settings": "/" };

function route(path: string): ReactNode {
  let m: Record<string, string> | null;
  if (path === "/") return <Summary />;
  if (path === "/settings") return <Settings />;
  if (path === "/settings/health") return <HealthSetup />;
  if (path === "/settings/region") return <RegionPage />;
  if (path === "/settings/whoop") return <WhoopSetup />;
  if (path === "/health") return <HealthPage />;
  if ((m = match("/health/:key", path))) return <MetricPage metricKey={m.key ?? ""} />;
  if (path === "/settings/notifications") return <NotificationsPage />;
  if (path === "/settings/backups") return <BackupsPage />;
  if (path === "/diet") return <Today />;
  if (path === "/diet/goals") return <Goals />;
  if (path === "/diet/drinks") return <DrinksPage />;
  if (path === "/diet/history") return <HistoryPage />;
  if ((m = match("/diet/meal/:id", path))) return <MealPage id={Number(m.id)} />;
  if (path === "/assistant") return <AssistantHome />;
  if (path === "/assistant/profile") return <ProfilePage />;
  if (path === "/assistant/sessions") return <SessionsPage />;
  if ((m = match("/assistant/task/:id", path))) return <TaskPage id={Number(m.id)} />;
  return (
    <Page title="Not Found" backTo="/" backLabel="Summary">
      <div className="empty">
        <img src="/icons/icon.svg?v=6" alt="" width={88} height={88} />
        <p>Hobbes couldn't sniff this one out.</p><Link to="/">Go to Summary</Link>
      </div>
    </Page>
  );
}

function UpdateBanner() {
  const available = useUpdateAvailable();
  if (!available) return null;
  return (
    <div className="update-banner" role="status">
      <span>Hobbes learned a new trick</span>
      <button type="button" className="button small" onClick={hardReload}>Reload</button>
    </div>
  );
}

export function App() {
  const path = usePath();
  const top = "/" + (path.split("/")[1] ?? "");
  const current = (t: Tab) => (t.path === "/" ? path === "/" : top === t.path);
  const currentTab = (t: Tab) => current(t) || TAB_OF[top] === t.path;
  return (
    <ToastHost>
      <div className="shell">
        <a className="skip" href="#main">Skip to content</a>
        <UpdateBanner />
        <nav className="sidebar" aria-label="Sections">
          <div className="sidebar-title">Hobbes at Home</div>
          {SECTIONS.map((t) => (
            <Link key={t.path} to={t.path} className="side-link" aria-current={current(t) ? "page" : undefined}>
              {t.icon(false)}
              {t.label}
            </Link>
          ))}
          <div style={{ flex: 1 }} />
          <Link to="/settings" className="side-link" aria-current={path.startsWith("/settings") ? "page" : undefined}>
            <GearIcon />Settings
          </Link>
        </nav>
        <div className="content">{route(path)}</div>
        <nav className="tabbar" aria-label="Sections">
          {SECTIONS.map((t) => (
            <Link key={t.path} to={t.path} className="tab" aria-current={currentTab(t) ? "page" : undefined}>
              {t.icon(currentTab(t))}
              <span>{t.label}</span>
            </Link>
          ))}
        </nav>
      </div>
    </ToastHost>
  );
}
