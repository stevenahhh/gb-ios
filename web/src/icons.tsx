import type { CSSProperties } from "react";

const stroke: Record<string, string> = {
  house: "M3.5 11 12 4l8.5 7v8.5a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z",
  calendar: "M4 6.5h16v13.5H4z M4 10.5h16 M8.5 3.5v4 M15.5 3.5v4",
  calendarCheck: "M4 6.5h16v13.5H4z M4 10.5h16 M8.5 3.5v4 M15.5 3.5v4 M9 15.5l2 2 4-4",
  calendarPlus: "M4 6.5h16v13.5H4z M4 10.5h16 M8.5 3.5v4 M15.5 3.5v4 M12 13v5 M9.5 15.5h5",
  grid: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  plus: "M12 5v14 M5 12h14",
  search: "M10.5 4.5a6 6 0 1 1 0 12 6 6 0 0 1 0-12z M15 15l5 5",
  chevronRight: "M9.5 5.5 16 12l-6.5 6.5",
  chevronLeft: "M14.5 5.5 8 12l6.5 6.5",
  chevronDown: "M6 9.5l6 6 6-6",
  xmark: "M6.5 6.5l11 11 M17.5 6.5l-11 11",
  arrowUp: "M12 19V5.5 M6 11.5l6-6 6 6",
  sort: "M7.5 4v16 M3.5 8l4-4 4 4 M16.5 20V4 M12.5 16l4 4 4-4",
  circle: "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z",
  progress: "M4.5 12a7.5 7.5 0 0 1 13-5 M19.5 12a7.5 7.5 0 0 1-13 5 M18 3.5V7h-3.5 M6 20.5V17h3.5",
  bag: "M5 8.5h14l-1.2 11.5H6.2z M9 8.5V7a3 3 0 0 1 6 0v1.5",
  box: "M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z M3.5 7.5 12 11.5l8.5-4 M12 11.5v9",
  checklist: "M10 6.5h10 M10 12h10 M10 17.5h10 M3.5 6.5 5 8l2.5-2.5 M3.5 12 5 13.5 7.5 11 M3.5 17.5 5 19l2.5-2.5",
  bubbles: "M3.5 4.5h11v7.5H8l-4.5 3.5z M10 15h6l4.5 3.5V9H17",
  bubble: "M4 4.5h16v11.5H9l-5 4z",
  won: "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z M7.5 8.5l1.7 7L12 9.5l2.8 6 1.7-7 M7 12h10",
  storefront: "M4.5 10.5V20h15v-9.5 M3.5 6.5 5.5 3.5h13l2 3v1.5a3 3 0 0 1-5.7 1.3 3 3 0 0 1-5.6 0A3 3 0 0 1 3.5 8z M10 20v-5h4v5",
  docText: "M6 3.5h8.5L19 8v12.5H6z M14 3.5V8h5 M9 12.5h7 M9 16h7",
  textBubble: "M4 4.5h16v11.5H9l-5 4z M8 8.5h8 M8 12h5",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3A4 4 0 0 0 13 5.3l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1",
  person2: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M3.5 19.5a5.5 5.5 0 0 1 11 0 M15.5 5a3 3 0 0 1 0 6 M17.5 14.5a5.5 5.5 0 0 1 3 5",
  bell: "M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z M10 20.5a2 2 0 0 0 4 0",
  personCircle: "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z M12 7.5a3 3 0 1 1 0 6 3 3 0 0 1 0-6z M6.5 18a6.5 6.5 0 0 1 11 0",
  question: "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z M9.8 9.5a2.3 2.3 0 1 1 3.2 2.1c-.6.3-1 .8-1 1.5v.6 M12 16.6v.1",
  tray: "M3.5 13.5 6.5 5h11l3 8.5V19a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1z M3.5 13.5h5l1 2h5l1-2h5",
  wifiExcl: "M2.5 9a14 14 0 0 1 19 0 M5.5 12.5a9.5 9.5 0 0 1 13 0 M12 15.5v.1 M12 19.5v.1",
  chart: "M4 20h16 M7.5 16.5v-5 M12 16.5v-9 M16.5 16.5v-7",
  hammer: "M13.5 4.5l6 6-2.5 2.5-6-6z M11 7 3.5 14.5l3 3L14 10",
  infoCircle: "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z M12 11v5.5 M12 8v.1",
  uturn: "M9 14 4.5 9.5 9 5 M4.5 9.5H14a5.5 5.5 0 0 1 0 11h-2",
  flag: "M6 21V4 M6 4.5h12l-3 4 3 4H6",
  checkmark: "M5 12.5l4.5 4.5L19 7.5",
};

const filled: Record<string, { fill: string; inner?: string }> = {
  checkFill: { fill: "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z", inner: "M7.5 12.2l3 3 6-6.2" },
  exclFill: { fill: "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z", inner: "M12 7v6.5 M12 16.5v.3" },
  clockFill: { fill: "M12 2.5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19z", inner: "M12 7v5.5l3.5 2" },
  sparkles: { fill: "M11 3l1.9 5.6L18.5 10.5l-5.6 1.9L11 18l-1.9-5.6L3.5 10.5l5.6-1.9z M18.5 14.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z" },
  mic: { fill: "M12 2.5a3.5 3.5 0 0 0-3.5 3.5v6a3.5 3.5 0 0 0 7 0V6A3.5 3.5 0 0 0 12 2.5z", inner: "" },
  gear: { fill: "M10.3 2.5h3.4l.5 2.6 1.7.8 2.2-1.5 2.4 2.4-1.5 2.2.8 1.7 2.6.5v3.4l-2.6.5-.8 1.7 1.5 2.2-2.4 2.4-2.2-1.5-1.7.8-.5 2.6h-3.4l-.5-2.6-1.7-.8-2.2 1.5-2.4-2.4 1.5-2.2-.8-1.7-2.6-.5v-3.4l2.6-.5.8-1.7-1.5-2.2 2.4-2.4 2.2 1.5 1.7-.8z M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8z" },
  houseFill: { fill: "M3 11.2 12 3.8l9 7.4V20a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z" },
  gridFill: { fill: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z" },
  calendarFill: { fill: "M4 6h16v15H4z", inner: "M4 10.5h16 M8.5 3.5v4 M15.5 3.5v4" },
};

type Props = { name: string; size?: number; color?: string; weight?: number; style?: CSSProperties; label?: string };

export function Icon({ name, size = 22, color = "currentColor", weight = 1.8, style, label }: Props) {
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true };
  const f = filled[name];
  if (f) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" style={style} {...a11y}>
        <path d={f.fill} fill={color} fillRule="evenodd" />
        {name === "mic" ? <path d="M6 11.5a6 6 0 0 0 12 0 M12 17.5V21" stroke={color} strokeWidth={1.8} fill="none" strokeLinecap="round" /> : null}
        {f.inner ? <path d={f.inner} stroke={name === "calendarFill" ? "var(--cell)" : "#fff"} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /> : null}
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={style} {...a11y}>
      <path d={stroke[name] ?? stroke.circle} stroke={color} strokeWidth={weight} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
