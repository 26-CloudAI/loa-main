// BattleRoyale2 백엔드 베이스 URL 결정.
// 앱 전체가 VITE_API_BASE(.../battleroyale)로 백엔드를 가리키므로, 거기서 /battleroyale2 로 파생한다.
// (별도 VITE_BR2_API_BASE 가 명시돼 있으면 우선 사용)
//   - 개발: http://localhost:8080/battleroyale → http://localhost:8080/battleroyale2
//   - 배포: https://...run.app/battleroyale     → https://...run.app/battleroyale2

const _RAW_API = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8080/battleroyale'
const _DERIVED = _RAW_API.replace(/\/battleroyale\/?$/, '/battleroyale2')

/** REST 베이스. 예: https://host/battleroyale2 */
export const BR2_API_BASE: string =
  (import.meta.env.VITE_BR2_API_BASE as string | undefined) ?? _DERIVED

/** WS 매치 베이스(끝에 /match/). 예: wss://host/battleroyale2/match/ */
export const BR2_WS_BASE: string = BR2_API_BASE.replace(/^http/, 'ws') + '/match/'
