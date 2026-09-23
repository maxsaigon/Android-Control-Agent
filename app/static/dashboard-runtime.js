// Small browser primitives shared by dashboard sections.
export function pollVisible(callback, interval) {
    let busy = false;
    async function refresh() {
        if (document.hidden || busy) return;
        busy = true;
        try { await callback(); }
        finally { busy = false; }
    }
    const timer = setInterval(() => { refresh().catch(console.error); }, interval);
    const visible = () => { if (!document.hidden) refresh().catch(console.error); };
    document.addEventListener('visibilitychange', visible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
}

export function reconcileCards(container, html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    const nextGrid = template.content.firstElementChild;
    const grid = container.firstElementChild;
    if (!grid || !grid.classList.contains('device-grid') || !nextGrid?.classList.contains('device-grid')) {
        container.replaceChildren(template.content);
        return;
    }
    const ids = new Set();
    Array.from(nextGrid.children).forEach((next, index) => {
        ids.add(next.id);
        let old = Array.from(grid.children).find(node => node.id === next.id);
        if (old?.classList.contains('selected')) next.classList.add('selected');
        if (old?.contains(document.activeElement) && document.activeElement.matches('input')) return;
        if (!old) old = next;
        else if (old.outerHTML !== next.outerHTML) { old.replaceWith(next); old = next; }
        if (grid.children[index] !== old) grid.insertBefore(old, grid.children[index] || null);
    });
    Array.from(grid.children).forEach(node => { if (!ids.has(node.id)) node.remove(); });
}
