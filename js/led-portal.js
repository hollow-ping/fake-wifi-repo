/**
 * Tell the Pi status LEDs when a guest is on a "connecting" screen.
 * Each browser tab has its own id so intranet idle from one person cannot
 * cancel connecting from another. leds.py uses the max of everyone.
 *
 * Usage:
 *   <script src="/js/led-portal.js"></script>
 *   <script>BurnerLedPortal.connecting();</script>   // connect flow pages
 *   <script>BurnerLedPortal.idle();</script>         // intranet / leave flow
 */
(function (global) {
    const ENDPOINT = '/api/led-portal';
    const ID_KEY = 'burnerLedId';
    let timer = null;

    function clientId() {
        try {
            let id = sessionStorage.getItem(ID_KEY);
            if (!id) {
                id = Math.random().toString(36).slice(2) + Date.now().toString(36);
                sessionStorage.setItem(ID_KEY, id);
            }
            return id;
        } catch (e) {
            return 'anon';
        }
    }

    function post(phase) {
        try {
            fetch(ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phase: phase, client: clientId() }),
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
