export type TimelineItem = {
  item_id: string;
  item_type: string;
  content: string;
  layer: string;
  created_at: string;
};

type TimelinePanelProps = {
  items: TimelineItem[];
};

export function TimelinePanel({ items }: TimelinePanelProps) {
  if (items.length === 0) {
    return <p className="empty-state">No events or promoted memories yet for this session.</p>;
  }
  return (
    <ol className="timeline-list">
      {items.map((item) => (
        <li key={item.item_id}>
          {new Date(item.created_at).toLocaleString()} - {item.layer}: {item.content}
        </li>
      ))}
    </ol>
  );
}
