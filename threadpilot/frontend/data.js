/* Live database snapshot. No bundled data fallback. */
(async function loadDatabaseSnapshot() {
  const app = document.getElementById('app');
  app.textContent = 'Loading current factory records…';
  try {
    const response = await fetch('/api/snapshot', {cache: 'no-store'});
    if (!response.ok) throw new Error('Database unavailable. Check migrations and connection settings.');
    const data = await response.json();
    if (!data.orders?.length || !data.production_log?.length || !data.workshops?.length)
      throw new Error('Import orders, production_log and workshops before opening the dashboard.');
    if (!['KNITTING', 'ASSEMBLY', 'WASHING', 'PACKING'].every(stage => data.production_log.some(row => row.stage === stage && new Date(row.date + 'T12:00:00Z').getUTCDay() !== 0)))
      throw new Error('Dashboard needs a working-day production record for each stage. Data APIs remain available.');
    window.TRACK1_DATA = data;
    app.style.visibility = 'hidden';
    for (const file of ['app.js', 'data-views.js', 'ai-api.js', 'ai-stream.js']) {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = file; script.onload = resolve; script.onerror = reject;
        document.body.appendChild(script);
      });
    }
    app.style.visibility = '';
  } catch (error) {
    app.style.visibility = '';
    app.textContent = 'Unable to load current data: ' + (error.message || 'network error');
  }
})();
