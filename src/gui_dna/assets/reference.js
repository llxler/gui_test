// Independently authored GUI reference primitives, not copied from DNA.
// @function {"name":"deriveView","feature":"core","reads":["items","query","filter","sort","page","pageSize","enabled"],"writes":[],"requires":[],"pre":"Array.isArray(before.items)","post":"after.page >= 1 && after.page <= afterView.pages && new Set(after.items.map(x=>x.id)).size === after.items.length"}
function deriveView(s) {
  let items = s.items.filter(x => x.name.toLowerCase().includes(s.query.trim().toLowerCase()) && (s.filter === 'all' || x.category === s.filter));
  if (s.sort === 'name-asc') items.sort((a,b) => a.name.toLowerCase() < b.name.toLowerCase() ? -1 : a.name.toLowerCase() > b.name.toLowerCase() ? 1 : 0);
  if (s.sort === 'score-desc') items.sort((a,b) => b.score - a.score);
  const total = items.length;
  const pages = s.enabled.includes('pagination') ? Math.max(1, Math.ceil(total / s.pageSize)) : 1;
  if (s.enabled.includes('pagination')) items = items.slice((s.page-1)*s.pageSize, s.page*s.pageSize);
  return {items, total, pages};
}
// @end
// @function {"name":"search","feature":"search","reads":[],"writes":["query","page"],"requires":[],"pre":"typeof event.value === 'string'","post":"after.query === event.value && after.page === 1 && JSON.stringify(before.items) === JSON.stringify(after.items)"}
function search(s,e) { s.query = e.value; s.page = 1; }
// @end
// @function {"name":"filter","feature":"filter","reads":[],"writes":["filter","page"],"requires":[],"pre":"['all','A','B','C'].includes(event.value)","post":"after.filter === event.value && after.page === 1 && JSON.stringify(before.items) === JSON.stringify(after.items)"}
function filter(s,e) { s.filter = e.value; s.page = 1; }
// @end
// @function {"name":"sort","feature":"sort","reads":[],"writes":["sort","page"],"requires":[],"pre":"['none','name-asc','score-desc'].includes(event.value)","post":"after.sort === event.value && after.page === 1 && JSON.stringify(before.items) === JSON.stringify(after.items)"}
function sort(s,e) { s.sort = e.value; s.page = 1; }
// @end
// @function {"name":"pagination","feature":"pagination","reads":["page"],"writes":["page"],"requires":["deriveView"],"pre":"Number.isFinite(event.value)","post":"after.page >= 1 && after.page <= afterView.pages"}
function pagination(s,e) { s.page = Math.max(1, Math.trunc(e.value)); }
// @end
// @function {"name":"edit","feature":"edit","reads":["items","editing"],"writes":["editing","items"],"requires":[],"pre":"Array.isArray(before.items)","post":"event.type === 'save' || JSON.stringify(before.items) === JSON.stringify(after.items)"}
function edit(s,e) {
  if (e.type === 'edit') s.editing = structuredClone(s.items.find(x => x.id === e.id) ?? null);
  if (e.type === 'draft' && s.editing) s.editing[e.field] = e.value;
  if (e.type === 'cancel') s.editing = null;
  if (e.type === 'save' && s.editing) {
    s.items = s.items.map(x => x.id === s.editing.id ? {...s.editing} : x);
    s.editing = null;
  }
}
// @end
// @function {"name":"removeItem","feature":"delete","reads":["items","editing"],"writes":["items","history","editing"],"requires":[],"pre":"before.items.some(x=>x.id===event.id)","post":"!after.items.some(x=>x.id===event.id) && after.history.length === before.history.length + 1"}
function removeItem(s,e) {
  const index = s.items.findIndex(x => x.id === e.id);
  if (index < 0) return;
  s.history.push({item: structuredClone(s.items[index]), index});
  s.items.splice(index,1);
  if (s.editing?.id === e.id) s.editing = null;
}
// @end
// @function {"name":"undo","feature":"undo","reads":["history","items"],"writes":["history","items"],"requires":[],"pre":"Array.isArray(before.history)","post":"after.history.length === Math.max(0,before.history.length-1) && after.items.length === before.items.length + (before.history.length ? 1 : 0)"}
function undo(s,e) {
  const entry = s.history.pop();
  if (entry && !s.items.some(x => x.id === entry.item.id)) s.items.splice(entry.index,0,entry.item);
}
// @end
