/**
 * BotCodeInput
 *
 * 봇 코드 입력 방식을 탭으로 전환할 수 있는 공통 컴포넌트.
 *
 * - "직접 입력"      탭 : PythonEditor (CodeMirror)
 * - "파일 업로드"    탭 : .py 파일 드래그&드롭 / 클릭 업로드
 * - "프롬프트로 생성" 탭 : 자연어 → Gemini 코드 생성 (generateApiBase 제공 시 표시)
 *
 * Props:
 *   value            — 현재 코드 문자열
 *   onChange         — 코드가 바뀔 때 호출
 *   hasError         — 바이트 초과 등 에러 상태 (에디터 테두리 빨간색)
 *   accentColor      — 탭 활성 강조색 ('indigo' | 'red' | 'green' | 'gold'), 기본 'indigo'
 *   generateApiBase  — 코드 생성 API 베이스 URL (없으면 프롬프트 탭 숨김)
 *   generateMode     — 생성 요청에 포함할 모드 문자열 ('br2d' | 'boss' | 'stocks')
 */

import { useRef, useState, useCallback } from 'react'
import PythonEditor from './PythonEditor'

type AccentColor = 'indigo' | 'red' | 'green' | 'gold'

interface BotCodeInputProps {
  value: string
  onChange: (value: string) => void
  hasError?: boolean
  accentColor?: AccentColor
  generateApiBase?: string
  generateMode?: string
}

const ACCENT: Record<AccentColor, { active: string; ring: string; border: string; text: string }> = {
  indigo: {
    active: 'bg-indigo-600 text-white',
    ring:   'ring-indigo-500',
    border: 'border-indigo-500/40 hover:border-indigo-400',
    text:   'text-indigo-400',
  },
  red: {
    active: 'bg-red-700 text-white',
    ring:   'ring-red-500',
    border: 'border-red-500/40 hover:border-red-400',
    text:   'text-red-400',
  },
  green: {
    active: 'bg-green-700 text-white',
    ring:   'ring-green-500',
    border: 'border-green-500/40 hover:border-green-400',
    text:   'text-green-400',
  },
  gold: {
    active: 'text-white',
    ring:   'ring-[#F5A624]',
    border: 'border-[#F5A624]/40 hover:border-[#F5A624]',
    text:   'text-[#FFC76A]',
  },
}

type InputMode = 'editor' | 'upload' | 'prompt'

export default function BotCodeInput({
  value,
  onChange,
  hasError = false,
  accentColor = 'indigo',
  generateApiBase,
  generateMode,
}: BotCodeInputProps) {
  const ac = ACCENT[accentColor]
  const [mode, setMode] = useState<InputMode>('editor')
  const [uploadedFile, setUploadedFile] = useState<{ name: string; size: number } | null>(null)
  const [dragOver, setDragOver]         = useState(false)
  const [uploadError, setUploadError]   = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // 프롬프트 탭 상태
  const [promptText, setPromptText]     = useState('')
  const [generating, setGenerating]     = useState(false)
  const [generateError, setGenerateError] = useState('')
  const [generatedPreview, setGeneratedPreview] = useState<string | null>(null)

  const handleFile = useCallback((file: File) => {
    setUploadError('')

    if (!file.name.endsWith('.py')) {
      setUploadError('.py 파일만 업로드할 수 있습니다.')
      return
    }
    if (file.size > 50 * 1024) {
      setUploadError(`파일이 너무 큽니다 (${(file.size / 1024).toFixed(1)} KB / 50 KB 제한).`)
      return
    }

    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result as string
      onChange(text)
      setUploadedFile({ name: file.name, size: file.size })
    }
    reader.onerror = () => setUploadError('파일을 읽는 중 오류가 발생했습니다.')
    reader.readAsText(file, 'utf-8')
  }, [onChange])

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
    e.target.value = ''
  }

  function handleRemoveFile() {
    setUploadedFile(null)
    setUploadError('')
    onChange('')
  }

  function switchMode(next: InputMode) {
    setMode(next)
    if (next === 'editor') {
      setUploadedFile(null)
      setUploadError('')
    }
    if (next === 'prompt') {
      setGenerateError('')
      setGeneratedPreview(null)
    }
  }

  async function handleGenerate() {
    if (!promptText.trim() || !generateApiBase) return
    setGenerating(true)
    setGenerateError('')
    setGeneratedPreview(null)
    try {
      const res = await fetch(`${generateApiBase}/api/bots/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText.trim(), mode: generateMode ?? '' }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? `서버 오류 (${res.status})`)
      }
      const { code } = await res.json()
      setGeneratedPreview(code)
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : '코드 생성에 실패했습니다.')
    } finally {
      setGenerating(false)
    }
  }

  function applyGenerated() {
    if (!generatedPreview) return
    onChange(generatedPreview)
    setGeneratedPreview(null)
    setMode('editor')
  }

  const goldActive = accentColor === 'gold' ? { background: '#F5A624' } : {}

  function tabStyle(t: InputMode) {
    return [
      'flex items-center text-xs font-medium rounded-md py-1.5 transition-colors',
      mode === t ? ac.active : 'text-gray-400 hover:text-gray-200',
    ].join(' ')
  }

  return (
    <div className="flex flex-col gap-2">
      {/* ── 탭 전환 버튼 ── */}
      <div className="flex rounded-lg bg-gray-800 border border-gray-700 p-0.5 w-fit gap-0.5">
        <button
          type="button"
          onClick={() => switchMode('editor')}
          className={tabStyle('editor')}
          style={{ paddingLeft: 8, paddingRight: 12, ...(mode === 'editor' ? goldActive : {}) }}
        >
          <span style={{ fontSize: 11 }}>✏️</span>&nbsp;코드 직접입력
        </button>
        <button
          type="button"
          onClick={() => switchMode('upload')}
          className={tabStyle('upload')}
          style={{ paddingLeft: 8, paddingRight: 12, ...(mode === 'upload' ? goldActive : {}) }}
        >
          <span style={{ fontSize: 11 }}>📁</span>&nbsp;파일 업로드
        </button>
        {generateApiBase && (
          <button
            type="button"
            onClick={() => switchMode('prompt')}
            className={tabStyle('prompt')}
            style={{ paddingLeft: 8, paddingRight: 12, ...(mode === 'prompt' ? goldActive : {}) }}
          >
            <span style={{ fontSize: 11 }}>🖥️</span>&nbsp;프롬프트로 생성
          </button>
        )}
      </div>

      {/* ── 직접입력 모드 ── */}
      {mode === 'editor' && (
        <PythonEditor value={value} onChange={onChange} hasError={hasError} />
      )}

      {/* ── 파일 업로드 모드 ── */}
      {mode === 'upload' && (
        <div className="flex flex-col gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".py"
            className="hidden"
            onChange={handleInputChange}
          />

          {uploadedFile ? (
            <div className={[
              'rounded-xl border-2 px-5 py-4 flex items-center gap-4',
              hasError ? 'border-red-500/60 bg-red-500/5' : 'border-green-500/40 bg-green-500/5',
            ].join(' ')}>
              <span className="text-2xl shrink-0">🐍</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">{uploadedFile.name}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {(uploadedFile.size / 1024).toFixed(1)} KB
                  {hasError && <span className="text-red-400 ml-2">— 50KB 초과</span>}
                </p>
              </div>
              <div className="flex gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  className="text-xs text-gray-400 hover:text-white border border-gray-600 hover:border-gray-400 rounded-lg px-3 py-1.5 transition-colors"
                >
                  교체
                </button>
                <button
                  type="button"
                  onClick={handleRemoveFile}
                  className="text-xs text-red-400 hover:text-red-300 border border-red-700/50 hover:border-red-500 rounded-lg px-3 py-1.5 transition-colors"
                >
                  제거
                </button>
              </div>
            </div>
          ) : (
            <div
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onClick={() => inputRef.current?.click()}
              className={[
                'rounded-xl border-2 border-dashed px-6 py-12 flex flex-col items-center gap-3 cursor-pointer transition-all select-none',
                dragOver
                  ? 'border-gray-400 bg-gray-700/40 scale-[1.01]'
                  : 'border-gray-600 hover:border-gray-500 bg-gray-800/50 hover:bg-gray-800',
              ].join(' ')}
            >
              <span className="text-4xl">{dragOver ? '📂' : '📁'}</span>
              <div className="text-center">
                <p className="text-sm font-medium text-gray-200">
                  {dragOver ? '여기에 놓으세요' : '.py 파일을 드래그하거나 클릭해 선택'}
                </p>
                <p className="text-xs text-gray-500 mt-1">Python 파일 · 최대 50 KB</p>
              </div>
            </div>
          )}

          {uploadError && (
            <p className="text-xs text-red-400 flex items-center gap-1.5">
              <span>⚠️</span>{uploadError}
            </p>
          )}

          {uploadedFile && value && (
            <details className="group">
              <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-300 select-none transition-colors list-none flex items-center gap-1.5">
                <span className="group-open:rotate-90 transition-transform inline-block">▶</span>
                코드 미리보기
              </summary>
              <div className="mt-2">
                <PythonEditor value={value} onChange={onChange} hasError={hasError} />
              </div>
            </details>
          )}
        </div>
      )}

      {/* ── 프롬프트로 생성 모드 ── */}
      {mode === 'prompt' && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <textarea
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              placeholder={
                generateMode === 'stocks'
                  ? '어떤 투자 전략을 쓸지 설명해주세요.\n예) "뉴스 기반으로 상승 종목에 집중 투자하는 봇", "분산 투자로 안정적인 수익을 추구하는 봇"'
                  : generateMode === 'boss'
                  ? '보스전 전략을 설명해주세요.\n예) "보스를 피하면서 아이템을 먼저 챙기는 봇", "보스에게 정면으로 달려드는 공격적인 봇"'
                  : '어떤 전략의 봇을 만들고 싶은지 설명해주세요.\n예) "공격적으로 적에게 달려드는 봇", "코인만 먹고 자기장 피해 도망다니는 봇"'
              }
              rows={4}
              className="w-full rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-100 placeholder-gray-600 px-4 py-3 resize-none focus:outline-none focus:border-gray-500 transition-colors"
              disabled={generating}
            />
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating || !promptText.trim()}
              className={[
                'self-start flex items-center gap-2 text-sm font-medium rounded-lg pl-3 pr-4 py-2 transition-colors',
                generating || !promptText.trim()
                  ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white cursor-pointer',
              ].join(' ')}
            >
              {generating ? (
                <>
                  <span className="inline-block animate-spin">⏳</span>
                  <span>생성 중...</span>
                </>
              ) : (
                <><span>🖥️</span><span>코드 생성</span></>
              )}
            </button>
          </div>

          {generateError && (
            <p className="text-xs text-red-400 flex items-center gap-1.5">
              <span>⚠️</span>{generateError}
            </p>
          )}

          {generatedPreview && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">생성된 코드를 확인하고 적용하세요.</p>
                <button
                  type="button"
                  onClick={applyGenerated}
                  className="flex items-center gap-1.5 text-xs font-medium bg-green-700 hover:bg-green-600 text-white rounded-lg px-3 py-1.5 transition-colors"
                >
                  ✅ 에디터에 적용
                </button>
              </div>
              <PythonEditor value={generatedPreview} onChange={() => {}} readOnly hasError={false} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
