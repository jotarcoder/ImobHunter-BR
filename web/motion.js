(() => {
  const stage = document.querySelector('.hero-stage');
  const app = document.querySelector('.floating-app');
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

  if (stage && app) {
    let raf = 0;
    let targetX = 0, targetY = 0;
    let currentX = 0, currentY = 0;

    const render = () => {
      currentX += (targetX - currentX) * 0.085;
      currentY += (targetY - currentY) * 0.085;
      app.style.setProperty('--tilt-x', currentY.toFixed(2) + 'deg');
      app.style.setProperty('--tilt-y', currentX.toFixed(2) + 'deg');
      raf = 0;
    };

    const move = (event) => {
      if (reduce.matches) return;
      const rect = stage.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      targetX = Math.max(-5, Math.min(5, -y * 7));
      targetY = Math.max(-7, Math.min(7, x * 9));
      if (!raf) raf = requestAnimationFrame(render);
    };

    const leave = () => {
      targetX = 0;
      targetY = 0;
      if (!raf) raf = requestAnimationFrame(render);
    };

    stage.addEventListener('pointermove', move, { passive: true });
    stage.addEventListener('pointerleave', leave, { passive: true });
  }

  const revealItems = document.querySelectorAll('main section, .hero-copy');
  if ('IntersectionObserver' in window && !reduce.matches) {
    revealItems.forEach((item, index) => {
      item.classList.add('reveal-ready');
      item.style.transitionDelay = Math.min(index * 45, 180) + 'ms';
    });
    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    revealItems.forEach((item) => observer.observe(item));
  }

  const tiltItems = document.querySelectorAll('[data-tilt]');
  tiltItems.forEach((el) => {
    const depth = Number(el.dataset.depth || 10);
    el.addEventListener('pointermove', (event) => {
      if (reduce.matches) return;
      const rect = el.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.setProperty('--rx', (-y * 4.2).toFixed(2) + 'deg');
      el.style.setProperty('--ry', (x * 5.2).toFixed(2) + 'deg');
      el.style.setProperty('--tz', depth + 'px');
      el.style.setProperty('--field-x', (x * 100 + 50).toFixed(1) + '%');
      el.style.setProperty('--field-y', (y * 100 + 50).toFixed(1) + '%');
    }, { passive: true });
    el.addEventListener('pointerleave', () => {
      el.style.setProperty('--rx', '0deg');
      el.style.setProperty('--ry', '0deg');
      el.style.setProperty('--tz', '0px');
      el.style.setProperty('--field-x', '50%');
      el.style.setProperty('--field-y', '50%');
    }, { passive: true });
  });

  document.querySelectorAll('.button').forEach((el) => {
    el.addEventListener('pointermove', (event) => {
      if (reduce.matches) return;
      const rect = el.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.setProperty('--button-rx', (-y * 5).toFixed(2) + 'deg');
      el.style.setProperty('--button-ry', (x * 7).toFixed(2) + 'deg');
      el.style.setProperty('--button-z', '9px');
    }, { passive: true });
    el.addEventListener('pointerleave', () => {
      el.style.setProperty('--button-rx', '0deg');
      el.style.setProperty('--button-ry', '0deg');
      el.style.setProperty('--button-z', '0px');
    }, { passive: true });
    el.addEventListener('pointerdown', () => {
      if (!reduce.matches) el.style.setProperty('--button-z', '-2px');
    }, { passive: true });
  });
})();