(() => {
  const stage = document.querySelector('.hero-stage');
  const app = document.querySelector('.floating-app');
  if (!stage || !app) return;

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  let raf = 0;
  let targetX = 0, targetY = 0;
  let currentX = 0, currentY = 0;

  const render = () => {
    currentX += (targetX - currentX) * 0.08;
    currentY += (targetY - currentY) * 0.08;
    app.style.setProperty('--tilt-x', currentY.toFixed(2) + 'deg');
    app.style.setProperty('--tilt-y', currentX.toFixed(2) + 'deg');
    raf = 0;
  };

  const move = (event) => {
    if (reduce.matches) return;
    const rect = stage.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    targetX = x * 9;
    targetY = -y * 7;
    if (!raf) raf = requestAnimationFrame(render);
  };

  const leave = () => {
    targetX = 0;
    targetY = 0;
    if (!raf) raf = requestAnimationFrame(render);
  };

  stage.addEventListener('pointermove', move, { passive: true });
  stage.addEventListener('pointerleave', leave, { passive: true });

  const visual = app.querySelector('.demo-search b');
  if (visual) {
    visual.setAttribute('role', 'status');
    visual.setAttribute('aria-label', 'Visualização interativa');
  }
})();