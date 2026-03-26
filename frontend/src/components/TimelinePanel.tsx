import { AlertTriangle, BookOpenText, CheckCircle2, Clock3, Network } from "lucide-react";

export type TimelineItem = {
  item_id: string;
  item_type: string;
  content: string;
  layer: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

type TimelinePanelProps = {
  items: TimelineItem[];
};

export function TimelinePanel({ items }: TimelinePanelProps) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-6 text-center h-full text-secondary opacity-60">
        <Clock3 size={48} className="mb-4" />
        <p>No events or memories recorded in this session yet.</p>
      </div>
    );
  }

  function getLayerVisual(layer: string) {
    if (layer === "session" || layer === "event") {
      return {
        icon: <Clock3 size={18} className="text-brand" />,
        badgeClass: "badge-info",
      };
    }
    if (layer === "long_term" || layer === "retrieval_hint") {
      return {
        icon: <BookOpenText size={18} className="text-success" />,
        badgeClass: "badge-success",
      };
    }
    if (layer === "resolution") {
      return {
        icon: <CheckCircle2 size={18} className="text-success" />,
        badgeClass: "badge-success",
      };
    }
    if (layer === "failure") {
      return {
        icon: <AlertTriangle size={18} className="text-danger" />,
        badgeClass: "badge-info",
      };
    }
    return {
      icon: <Network size={18} className="text-brand" />,
      badgeClass: "badge-info",
    };
  }

  return (
    <div style={{ position: "relative", paddingLeft: "1rem", marginLeft: "0.75rem", marginTop: "1rem", borderLeft: "1px solid rgba(255,255,255,0.1)" }}>
      {items.map((item) => (
        <div key={item.item_id} className="animate-fade-in" style={{ position: "relative", marginBottom: "1.25rem" }}>
          <div style={{ position: "absolute", left: "-1.55rem", top: "0.25rem", background: "var(--bg-base)", borderRadius: "999px", padding: "0.1rem" }}>
            {getLayerVisual(item.layer).icon}
          </div>
          <div className="glass-panel" style={{ padding: "1rem" }}>
            <div className="flex justify-between mb-2" style={{ alignItems: "flex-start" }}>
              <span className={`badge ${getLayerVisual(item.layer).badgeClass}`}>
                {item.layer}
              </span>
              <span className="text-xs text-muted">
                {new Date(item.created_at).toLocaleString([], {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
            <p className="text-sm">{item.content}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
