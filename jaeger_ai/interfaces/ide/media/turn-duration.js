/* Shared by the Web UI and IDE. Extracted from the Web UI's turn clock. */
(function(root) {
  function formatTurnDuration(seconds) {
    const n=Number(seconds);
    if(!Number.isFinite(n)||n<0)return'';
    const total=Math.max(0,Math.round(n));
    if(total<60)return`${total}s`;
    const h=Math.floor(total/3600);
    const m=Math.floor((total%3600)/60);
    const s=total%60;
    if(h)return`${h}h ${m}m`;
    return`${m}m ${s}s`;
  }
  root.JaegerTurnDuration = { formatTurnDuration };
  if (typeof module === 'object') module.exports = root.JaegerTurnDuration;
})(typeof window === 'undefined' ? globalThis : window);
