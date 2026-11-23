import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'
export const LOCAL_VEHICLE_PREFIX: string
export function createHandler(readConfig: () => Record<string, string>): (req: IncomingMessage, res: ServerResponse, next: () => void) => void
export default function localVehicleAssets(opts: { configPath: string }): Plugin
