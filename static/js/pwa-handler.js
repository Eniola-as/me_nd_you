class PWAHandler {
  static async register() {
    if (!('serviceWorker' in navigator)) {
      return false;
    }

    try {
      const registration = await navigator.serviceWorker.register('/static/js/service-worker.js', {
        scope: '/'
      });

      // Setup messaging
      const messageChannel = new MessageChannel();
      messageChannel.port1.onmessage = (event) => {
        if (event.data.type === 'CONNECTED') {
          console.log('Service Worker connection established');
        }
      };

      if (registration.active) {
        registration.active.postMessage(
          { type: 'INIT_PORT' },
          [messageChannel.port2]
        );
      }

      // Handle updates
      registration.addEventListener('updatefound', () => {
        const newWorker = registration.installing;
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'activated') {
            window.location.reload();
          }
        });
      });

      return true;
    } catch (error) {
      console.error('Service Worker registration failed:', error);
      return false;
    }
  }
}

// Initialize when loaded
window.addEventListener('load', () => PWAHandler.register());
