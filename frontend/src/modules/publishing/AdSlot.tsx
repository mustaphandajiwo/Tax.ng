// Public display ad slot. Renders nothing when no approved, in-date ad exists,
// when the page is sensitive, or when the audience threshold is not yet met.
// Only the slot id and the page path are sent: never user or account data.
// Never use this inside /app (docs/MODULES.md, Annex B).
import { useEffect, useState } from "react";
import { pub, type Ad } from "./api";

function currentPage(): string {
  const path = window.location.hash.replace(/^#/, "");
  return path.startsWith("/") ? path.split("?")[0] : "/";
}

export function AdSlot({ slot, page }: { slot: string; page?: string }) {
  const [ad, setAd] = useState<Ad | null>(null);
  const where = page ?? currentPage();

  useEffect(() => {
    if (window.location.pathname.startsWith("/app")) return;
    let live = true;
    pub.slot(slot, where).then(
      (res) => {
        if (!live || !res.ad) return;
        setAd(res.ad);
        void pub.impression(res.ad.creative_id).catch(() => undefined);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [slot, where]);

  if (!ad) return null;
  const open = () => void pub.click(ad.creative_id).catch(() => undefined);
  return (
    <aside className="ad-slot" aria-label="Advertisement">
      <p className="ad-slot__label">{ad.label}</p>
      {ad.image_url && <img src={ad.image_url} alt="" className="pub-ad__image" />}
      <a href={ad.link_url} target="_blank" rel="noopener noreferrer sponsored" onClick={open}>
        <strong>{ad.headline}</strong>
      </a>
      {ad.body && <p className="small">{ad.body}</p>}
      <p className="muted small">From {ad.advertiser}</p>
    </aside>
  );
}
