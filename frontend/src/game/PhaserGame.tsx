import { useEffect, useRef } from 'react'
import Phaser from 'phaser'
import { BattleRoyaleScene } from './BattleRoyaleScene'
import type { TickData, GameEvent } from './BattleRoyaleScene'

interface Props {
  tickData:       TickData | null
  eventQueueRef:  { current: GameEvent[] }
  myBotId:        string   // 아이콘 주인 (고정, localStorage)
  followBotId:    string   // 카메라 추적 대상 (드롭박스로 변경 가능)
  myBotIcon:      string
  zoomLevel:      number
  onFollowChange: (botId: string) => void  // 관전 봇 사망 시 React 상태 동기화
  width:          number
  height:         number
}

export default function PhaserGame({
  tickData, eventQueueRef, myBotId, followBotId, myBotIcon, zoomLevel, onFollowChange,
  width, height,
}: Props) {
  const divRef   = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<BattleRoyaleScene | null>(null)
  const gameRef  = useRef<Phaser.Game | null>(null)

  // Create Phaser game once on mount
  useEffect(() => {
    if (!divRef.current) return

    const scene = new BattleRoyaleScene()
    // Wire the shared event queue ref before the scene starts
    scene.eventQueueRef = eventQueueRef

    const game = new Phaser.Game({
      type:            Phaser.AUTO,
      width,
      height,
      parent:          divRef.current,
      backgroundColor: '#0a0a0f',
      scene:           [scene],
      render:          { antialias: false, pixelArt: true },
      scale:           { mode: Phaser.Scale.NONE },
      banner:          false,
    })

    sceneRef.current = scene
    gameRef.current  = game

    return () => {
      game.destroy(true)
      sceneRef.current = null
      gameRef.current  = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Resize Phaser canvas when container size changes,
  // then reposition the minimap camera to stay bottom-right
  useEffect(() => {
    if (!gameRef.current) return
    gameRef.current.scale.resize(width, height)
    sceneRef.current?.resize(width)
  }, [width, height])

  // Sync tick data (Phaser reads from this ref each frame — no re-render)
  useEffect(() => {
    if (sceneRef.current) sceneRef.current.tickRef.current = tickData
  }, [tickData])

  // Sync icon owner (never changes mid-game)
  useEffect(() => {
    if (!sceneRef.current) return
    sceneRef.current.myBotId   = myBotId
    sceneRef.current.myBotIcon = myBotIcon
  }, [myBotId, myBotIcon])

  // Sync camera follow target (changes when user picks from dropdown)
  useEffect(() => {
    if (sceneRef.current) sceneRef.current.followBotId = followBotId
  }, [followBotId])

  // Sync zoom level (scene smoothly lerps toward it each frame)
  useEffect(() => {
    if (sceneRef.current) sceneRef.current.zoom = zoomLevel
  }, [zoomLevel])

  // Wire onFollowChange callback (scene calls this when followed bot dies)
  useEffect(() => {
    if (sceneRef.current) sceneRef.current.onFollowChange = onFollowChange
  }, [onFollowChange])

  return (
    <div
      ref={divRef}
      className="rounded-lg border border-gray-700 overflow-hidden"
      style={{ width, height, background: '#0a0a0f' }}
    />
  )
}
