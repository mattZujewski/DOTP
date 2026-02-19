/**
 * Chart.js 4.4.0 NaN/null layout fix
 *
 * Root cause: ticks.padding resolves to undefined → fit() computes
 * NaN/null for scale width/height → chartArea null → blank canvas.
 *
 * The NaN propagates through the layout pass (ss/ns functions) which also
 * resets scale geometry after fit(). Patching fit() alone is not sufficient
 * because the layout manager overwrites the fixed values.
 *
 * Fix: wrap Chart.layouts.update to sanitize ALL scale dimensions
 * (width, height, left, right, top, bottom, _length) after the full layout
 * pass completes, then force a chartArea recompute.
 */
(function () {
  if (typeof Chart === 'undefined' || !Chart.layouts || !Chart.layouts.update) return;

  function sanitizeNum(val, fallback) {
    return isFinite(val) && val !== null ? val : (fallback || 0);
  }

  const origUpdate = Chart.layouts.update;
  Chart.layouts.update = function (chart, width, height, padding) {
    const result = origUpdate.call(this, chart, width, height, padding);

    if (!chart || !chart.scales) return result;

    // After layout pass, check if any scales have null/NaN dimensions
    let needsRepair = false;
    for (const scale of Object.values(chart.scales)) {
      if (!isFinite(scale.width) || !isFinite(scale.height)) {
        needsRepair = true;
        break;
      }
    }
    if (!needsRepair) return result;

    // Repair each broken scale
    for (const scale of Object.values(chart.scales)) {
      const isH = scale.isHorizontal();

      if (!isH && !isFinite(scale.width)) {
        // Left/right axis: compute width from label sizes
        let labelW = 0;
        try {
          const sizes = scale._getLabelSizes && scale._getLabelSizes();
          labelW = (sizes && sizes.widest && sizes.widest.width) || 0;
        } catch (e) {}
        const pad = (scale.options && scale.options.ticks && +scale.options.ticks.padding) || 3;
        scale.width = Math.min(scale.maxWidth || 200, labelW + pad * 2 + 8);
        scale._length = scale.height;
      }

      if (isH && !isFinite(scale.height)) {
        // Top/bottom axis: compute height from label sizes
        let labelH = 0;
        try {
          const sizes = scale._getLabelSizes && scale._getLabelSizes();
          labelH = (sizes && sizes.highest && sizes.highest.height) || 0;
        } catch (e) {}
        const pad = (scale.options && scale.options.ticks && +scale.options.ticks.padding) || 3;
        scale.height = Math.min(scale.maxHeight || 60, labelH + pad * 2 + 8);
        scale._length = scale.width;
      }
    }

    // Recompute scale positions (left/right/top/bottom) from repaired widths/heights
    // Uses the same logic Chart.js uses internally: accumulate from edges
    const chartW = width || (chart.canvas && chart.canvas.width / (chart.currentDevicePixelRatio || 1)) || 0;
    const chartH = height || (chart.canvas && chart.canvas.height / (chart.currentDevicePixelRatio || 1)) || 0;

    let padLeft = 0, padRight = 0, padTop = 0, padBottom = 0;
    // First pass: measure padding contributions
    for (const scale of Object.values(chart.scales)) {
      if (!scale.options || !scale.options.display) continue;
      const pos = scale.position;
      if (pos === 'left')   padLeft   = Math.max(padLeft,   scale.width  || 0);
      if (pos === 'right')  padRight  = Math.max(padRight,  scale.width  || 0);
      if (pos === 'top')    padTop    = Math.max(padTop,    scale.height || 0);
      if (pos === 'bottom') padBottom = Math.max(padBottom, scale.height || 0);
    }

    // Apply chartArea from repaired padding
    const ca = {
      left:   padLeft,
      right:  chartW - padRight,
      top:    padTop,
      bottom: chartH - padBottom,
    };
    ca.width  = ca.right  - ca.left;
    ca.height = ca.bottom - ca.top;

    if (ca.width > 0 && ca.height > 0) {
      Object.assign(chart.chartArea, ca);

      // Update scale geometry to match repaired chartArea
      for (const scale of Object.values(chart.scales)) {
        const pos = scale.position;
        if (pos === 'left') {
          scale.left   = 0;
          scale.right  = ca.left;
          scale.top    = ca.top;
          scale.bottom = ca.bottom;
          scale.width  = ca.left;
          scale.height = ca.height;
          scale._length = ca.height;
        } else if (pos === 'right') {
          scale.left   = ca.right;
          scale.right  = chartW;
          scale.top    = ca.top;
          scale.bottom = ca.bottom;
          scale.width  = chartW - ca.right;
          scale.height = ca.height;
          scale._length = ca.height;
        } else if (pos === 'top') {
          scale.left   = ca.left;
          scale.right  = ca.right;
          scale.top    = 0;
          scale.bottom = ca.top;
          scale.width  = ca.width;
          scale.height = ca.top;
          scale._length = ca.width;
        } else if (pos === 'bottom') {
          scale.left   = ca.left;
          scale.right  = ca.right;
          scale.top    = ca.bottom;
          scale.bottom = chartH;
          scale.width  = ca.width;
          scale.height = chartH - ca.bottom;
          scale._length = ca.width;
        }
      }
    }

    return result;
  };
})();
