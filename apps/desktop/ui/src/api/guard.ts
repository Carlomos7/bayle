import type { BayleApi } from './BayleApi';
import type { Gateway } from './gateway/hub';
import { GatewayError } from './gateway/transport';

/**
 * Calls made while the engine isn't ready fail at once with a sentence, the
 * same for the mock and the desktop app, instead of hanging or reaching a
 * half-started engine. subscribe is always allowed (it listens, it doesn't ask).
 */
export function guardApi(api: BayleApi, gateway: Gateway): BayleApi {
  return new Proxy(api, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver) as unknown;
      if (prop === 'subscribe' || typeof value !== 'function') return value;
      return (...args: unknown[]) => {
        const s = gateway.current();
        if (s?.state !== 'ready') {
          const message = s?.state === 'starting' || s?.state === 'restarting' || !s ? "Bayle's engine is starting. Try again in a moment." : "Bayle's engine isn't running. Use Retry at the top of the window.";
          return Promise.reject(new GatewayError({ code: 'engine_unavailable', message }));
        }
        return (value as (...a: unknown[]) => unknown).apply(target, args);
      };
    },
  });
}
