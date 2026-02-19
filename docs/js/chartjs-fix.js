/**
 * Chart.js 4.4.0 NaN layout fix for horizontal bar charts (indexAxis: 'y')
 *
 * Root cause traced through Chart.js internals:
 *   1. ticks.padding resolves to undefined for scales in indexAxis:'y' charts
 *   2. fit() computes: t.width = Ks(grid) + titleSize + labelWidth + 2*undefined = NaN
 *   3. NaN width → chartArea.width = null → blank canvas
 *
 * Fix: patch the base Scale class prototype's fit() method to sanitize NaN/null
 * width and height after the calculation runs, using label sizes as the fallback.
 * Applied before the first chart is constructed via Chart.prototype.initialize hook.
 */
(function () {
  if (typeof Chart === 'undefined') return;

  let fitPatched = false;

  function patchFit() {
    if (fitPatched) return;
    const scaleTypes = ['category', 'linear'];
    for (const type of scaleTypes) {
      const ScaleClass = Chart.registry && Chart.registry.scales && Chart.registry.scales.get(type);
      if (!ScaleClass) continue;
      let proto = ScaleClass.prototype;
      while (proto && proto !== Object.prototype) {
        if (proto.hasOwnProperty('fit') && proto.hasOwnProperty('_handleMargins')) {
          const origFit = proto.fit;
          proto.fit = function () {
            origFit.apply(this, arguments);
            // Sanitize NaN/null width (left/right positioned scales)
            if (!this.isHorizontal() && !isFinite(this.width)) {
              try {
                const sizes = this._getLabelSizes();
                const labelW = (sizes && sizes.widest && sizes.widest.width) || 0;
                const pad = (this.options && this.options.ticks && +this.options.ticks.padding) || 3;
                this.width = Math.min(this.maxWidth || 200, labelW + pad * 2 + 8);
              } catch (e) {
                this.width = this.maxWidth || 0;
              }
            }
            // Sanitize NaN/null height (top/bottom positioned scales)
            if (this.isHorizontal() && !isFinite(this.height)) {
              this.height = this.maxHeight || 0;
            }
          };
          fitPatched = true;
          break;
        }
        proto = Object.getPrototypeOf(proto);
      }
      if (fitPatched) break;
    }
  }

  // Apply before each chart is initialized
  const origInit = Chart.prototype.initialize;
  if (origInit) {
    Chart.prototype.initialize = function () {
      patchFit();
      return origInit.apply(this, arguments);
    };
  }

  // Belt-and-suspenders: also sanitize NaN margins in scale.update() calls
  const origLayoutsUpdate = Chart.layouts.update;
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
          margins ? {
            left:   isFinite(margins.left)   ? margins.left   : 0,
            right:  isFinite(margins.right)  ? margins.right  : 0,
            top:    isFinite(margins.top)    ? margins.top    : 0,
            bottom: isFinite(margins.bottom) ? margins.bottom : 0,
          } : margins
        );
      };
    }
    const result = origLayoutsUpdate.call(this, chart, width, height, padding);
    for (const [scale, origUpdate] of saved) {
      scale.update = origUpdate;
    }
    return result;
  };
})();
