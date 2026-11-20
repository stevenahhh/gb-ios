import { StrictMode, useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { assertNever } from "./data";
import { Icon } from "./icons";
import { AreaScreen } from "./area";
import { BookingDetailScreen, WorkDetailScreen } from "./details";
import { DraftDetailScreen } from "./drafts";
import { AssistantSheet, CalendarScreen, OperationsScreen, PlaceholderScreen, SettingsScreen, TodayScreen } from "./screens";
import { attentionCount, StoreProvider, useStore } from "./store";
import { NavContext, type Route } from "./ui";

const CANVAS_W = 402;
const CANVAS_H = Math.round((CANVAS_W * 19.5) / 9);
const MARGIN = 24;

type Tab = "today" | "calendar" | "operations" | "settings";
const tabs: { id: Tab; label: string; icon: string; activeIcon: string }[] = [
  { id: "today", label: "오늘", icon: "house", activeIcon: "houseFill" },
  { id: "calendar", label: "캘린더", icon: "calendar", activeIcon: "calendarFill" },
  { id: "operations", label: "운영", icon: "grid", activeIcon: "gridFill" },
  { id: "settings", label: "설정", icon: "gear", activeIcon: "gear" },
];

type Layer = { key: number; route: Route; leaving?: boolean };

function useFitScale() {
  const compute = () => Math.min((window.innerWidth - MARGIN * 2) / CANVAS_W, (window.innerHeight - MARGIN * 2) / CANVAS_H);
  const [scale, setScale] = useState(compute);
  useLayoutEffect(() => {
    const onResize = () => setScale(compute());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return Math.max(scale, 0.1);
}

const wideQuery = window.matchMedia("(min-width: 720px)");
function useWide() {
  const [wide, setWide] = useState(wideQuery.matches);
  useLayoutEffect(() => {
    const onChange = () => setWide(wideQuery.matches);
    wideQuery.addEventListener("change", onChange);
    return () => wideQuery.removeEventListener("change", onChange);
  }, []);
  return wide;
}

function RootScreen({ tab }: { tab: Tab }) {
  switch (tab) {
    case "today": return <TodayScreen />;
    case "calendar": return <CalendarScreen />;
    case "operations": return <OperationsScreen />;
    case "settings": return <SettingsScreen />;
    default: return assertNever(tab);
  }
}

function RouteView({ tab, route }: { tab: Tab; route: Route }) {
  switch (route.kind) {
    case "root": return <RootScreen tab={tab} />;
    case "area": return <AreaScreen areaId={route.area} initialFilter={route.filter} />;
    case "booking": return <BookingDetailScreen id={route.id} />;
    case "work": return <WorkDetailScreen id={route.id} />;
    case "draft": return <DraftDetailScreen id={route.id} />;
    case "placeholder": return <PlaceholderScreen title={route.title} symbol={route.symbol} />;
    default: return assertNever(route);
  }
}

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const forced = new URLSearchParams(location.search).get("theme");
  document.documentElement.dataset.theme = forced === "dark" || forced === "light" ? forced : darkQuery.matches ? "dark" : "light";
}
applyTheme();
darkQuery.addEventListener("change", applyTheme);

let layerKey = 0;

function TabStack({ tab, active }: { tab: Tab; active: boolean }) {
  const [layers, setLayers] = useState<Layer[]>([{ key: layerKey++, route: { kind: "root" } }]);
  const reduceMotion = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const push = useCallback((route: Route) => setLayers((l) => [...l, { key: layerKey++, route }]), []);
  const pop = useCallback(() => {
    setLayers((l) => {
      if (l.length < 2) return l;
      if (reduceMotion) return l.slice(0, -1);
      return l.map((layer, i) => (i === l.length - 1 ? { ...layer, leaving: true } : layer));
    });
  }, [reduceMotion]);
  const nav = useMemo(() => ({ push, pop }), [push, pop]);
  const top = layers.length - 1;
  return (
    <NavContext.Provider value={nav}>
      <div className="stack" style={{ display: active ? "block" : "none" }}>
        {layers.map((layer, i) => {
          const covered = i < top && !(i === top - 1 && layers[top]?.leaving);
          const cls = ["layer", i > 0 && !layer.leaving ? "layer-enter" : "", layer.leaving ? "layer-leave" : "", covered ? "layer-covered" : ""].join(" ");
          return (
            <div
              key={layer.key}
              className={cls}
              aria-hidden={covered || layer.leaving ? true : undefined}
              onAnimationEnd={(e) => {
                if (layer.leaving && e.animationName === "slide-out") setLayers((l) => l.filter((x) => x.key !== layer.key));
              }}
            >
              <RouteView tab={tab} route={layer.route} />
            </div>
          );
        })}
      </div>
    </NavContext.Provider>
  );
}

function StatusBar() {
  return (
    <div className="statusbar" aria-hidden="true">
      <span className="status-time">9:41</span>
      <span className="status-icons">
        <svg width="18" height="12" viewBox="0 0 18 12"><rect x="0" y="8" width="3" height="4" rx="1" /><rect x="5" y="5.5" width="3" height="6.5" rx="1" /><rect x="10" y="3" width="3" height="9" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" /></svg>
        <svg width="16" height="12" viewBox="0 0 16 12"><path d="M8 2.2c2.4 0 4.6.9 6.2 2.5l1.3-1.4A10.6 10.6 0 0 0 8 .2 10.6 10.6 0 0 0 .5 3.3l1.3 1.4A8.7 8.7 0 0 1 8 2.2zm0 3.7c1.4 0 2.7.5 3.6 1.4l1.3-1.4A7 7 0 0 0 8 3.9a7 7 0 0 0-4.9 2l1.3 1.4c1-.9 2.2-1.4 3.6-1.4zM8 9.6 9.9 7.7a2.7 2.7 0 0 0-3.8 0z" /></svg>
        <svg width="27" height="13" viewBox="0 0 27 13"><rect x=".5" y=".5" width="23" height="12" rx="3.8" fill="none" stroke="currentColor" opacity=".4" /><rect x="2.5" y="2.5" width="19" height="8" rx="2.2" /><path d="M25 4.5v4a2 2 0 0 0 0-4z" opacity=".45" /></svg>
      </span>
    </div>
  );
}

function TabBar({ tab, onSelect }: { tab: Tab; onSelect: (t: Tab) => void }) {
  const { state } = useStore();
  const attention = attentionCount(state);
  return (
    <nav className="tabbar" aria-label="탭">
      {tabs.map((t) => (
        <button key={t.id} className={t.id === tab ? "tab tab-on" : "tab"} onClick={() => onSelect(t.id)} aria-current={t.id === tab ? "page" : undefined}>
          <span className="tab-icon">
            <Icon name={t.id === tab ? t.activeIcon : t.icon} size={24} />
            {t.id === "operations" && attention > 0 ? <span className="tab-badge" aria-label={`먼저 확인할 일 ${attention}건`}>{attention}</span> : null}
          </span>
          <span className="tab-label">{t.label}</span>
        </button>
      ))}
    </nav>
  );
}

function PhoneFrame({ children }: { children: ReactNode }) {
  const scale = useFitScale();
  useEffect(() => {
    document.documentElement.style.setProperty("--canvas-w", `${CANVAS_W}px`);
    document.documentElement.style.setProperty("--canvas-h", `${CANVAS_H}px`);
  }, []);
  return (
    <div className="stage">
      <div className="device" style={{ width: CANVAS_W * scale, height: CANVAS_H * scale }} data-testid="phone">
        <div className="canvas" style={{ width: CANVAS_W, height: CANVAS_H, transform: `scale(${scale})` }}>
          {children}
          <StatusBar />
          <div className="home-indicator" />
        </div>
      </div>
    </div>
  );
}

function App() {
  const wide = useWide();
  const [tab, setTab] = useState<Tab>("today");
  const [sheet, setSheet] = useState<null | { voice: boolean }>(null);
  const content = (
    <>
      {tabs.map((t) => <TabStack key={t.id} tab={t.id} active={t.id === tab} />)}
      <div className="accessory">
        <button className="accessory-main" onClick={() => setSheet({ voice: false })} aria-label="비서에게 물어보기">
          <Icon name="sparkles" size={20} color="var(--accent)" />
          <span>비서에게 물어보세요</span>
        </button>
        <button className="accessory-mic" onClick={() => setSheet({ voice: true })} aria-label="말로 물어보기">
          <Icon name="mic" size={20} />
        </button>
      </div>
      <TabBar tab={tab} onSelect={setTab} />
      {sheet ? <AssistantSheet voice={sheet.voice} onClose={() => setSheet(null)} /> : null}
    </>
  );
  if (wide) {
    return (
      <div className="stage">
        <div className="canvas canvas-wide" data-testid="canvas">{content}</div>
      </div>
    );
  }
  return <PhoneFrame>{content}</PhoneFrame>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </StrictMode>,
);
