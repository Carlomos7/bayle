import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Which section is in view inside the page's scroll container (#scroll).
 * `jump` scrolls to a section and holds the highlight there while the
 * smooth scroll runs, so the nav doesn't flicker through the ones it passes.
 */
export function useScrollSpy(ids: string[], ready: boolean, offset = 90) {
  const [active, setActive] = useState(ids[0] ?? '');
  const lock = useRef(0);
  const key = ids.join('|');

  useEffect(() => {
    const sc = document.getElementById('scroll');
    if (!sc) return;
    const onScroll = () => {
      if (Date.now() - lock.current < 700) return;
      const top = sc.getBoundingClientRect().top + offset;
      let cur = ids[0];
      ids.forEach((id) => { const el = document.getElementById(`set-${id}`); if (el && el.getBoundingClientRect().top <= top) cur = id; });
      if (sc.scrollTop > 0 && sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 4) cur = ids[ids.length - 1];
      if (cur) setActive(cur);
    };
    onScroll();
    sc.addEventListener('scroll', onScroll, { passive: true });
    return () => sc.removeEventListener('scroll', onScroll);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- key stands in for ids
  }, [key, offset, ready]);

  const jump = useCallback((id: string) => {
    lock.current = Date.now();
    setActive(id);
    document.getElementById(`set-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  return { active, jump };
}
