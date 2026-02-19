/**
 * Chart.js 4.4.0 NaN layout fix
 *
 * Root cause: _calculatePadding() can produce NaN for paddingLeft/Right on
 * LinearScale axes. This propagates through the layout engine's is() function
 * into g.left/right/top/bottom, poisoning the margins passed to all other scales.
 * The result: chartArea.width/height = null and all charts render blank.
 *
 * Fix: wrap Chart.layouts.update to intercept each scale's update() call
 * and sanitize any NaN/null values in maxW, maxH, and margins before they
 * enter the scale's fit() pipeline.
 */
(function () {
  if (typeof Chart === 'undefined') return;

  const orig = Chart.layouts.update;
  Chart.layouts.update = function (chart, width, height, padding) {
    const scales = chart && chart.scales ? Object.values(chart.scales) : [];
    const saved = new Map();

    for (const scale of scales) {
      const origUpdate = scale.update;
      saved.set(scale, origUpdate);
      scale.update = function (maxW, maxH, margins) {
        return origUpdate.call(
          this,
          isFinite(maxW) ? maxW : (this.maxWidth || 0),
          isFinite(maxH) ? maxH : (this.maxHeight || 0),
          margins
            ? {
                left:   isFinite(margins.left)   ? margins.left   : 0,
                right:  isFinite(margins.right)  ? margins.right  : 0,
                top:    isFinite(margins.top)    ? margins.top    : 0,
                bottom: isFinite(margins.bottom) ? margins.bottom : 0,
              }
            : margins
        );
      };
    }

    const result = orig.call(this, chart, width, height, padding);

    for (const [scale, origUpdate] of saved) {
      scale.update = origUpdate;
    }

    return result;
  };
})();
