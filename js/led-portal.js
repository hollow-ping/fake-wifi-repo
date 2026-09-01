/**
 * Tell the Pi status LEDs when a guest is on a "connecting" screen.
 * Heartbeats keep the rainbow alive; stale heartbeats expire in leds.py.
 *
 * Usage:
 *   <script src="/js/led-portal.js"></script>
 *   <script>BurnerLedPortal.connecting();</script>   // connect flow pages
 *   <script>BurnerLedPortal.idle();</script>         // leave connect flow
 */
(function (global) {
    const ENDPOINT = '/api/led-portal';
    let timer = null;

    function post(phase) {
        try {
            fetch(ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phase: phase }),
                keepalive: true,
                cache: 'no-store',
            }).catch(function () {});
        } catch (e) {}
    }

    function stopHeartbeat() {
        if (timer) {
            clearInterval(timer);
            timer = null;
        }
    }

    function connecting() {
        stopHeartbeat();
        post('connecting');
        timer = setInterval(function () { post('connecting'); }, 2500);
    }

    function idle() {
        stopHeartbeat();
        post('idle');
    }

    global.BurnerLedPortal = { connecting: connecting, idle: idle };
})(window);
