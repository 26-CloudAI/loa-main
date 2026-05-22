import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'

interface PythonEditorProps {
  value: string
  onChange: (value: string) => void
  hasError?: boolean
  readOnly?: boolean
  height?: string
}

export default function PythonEditor({ value, onChange, hasError, readOnly = false, height = '480px' }: PythonEditorProps) {
  return (
    <div
      style={{
        borderRadius: 8,
        overflow: 'hidden',
        border: `1px solid ${hasError ? '#ef4444' : '#374151'}`,
        outline: hasError ? '2px solid rgba(239,68,68,.3)' : undefined,
      }}
    >
      <CodeMirror
        value={value}
        height={height}
        theme={vscodeDark}
        extensions={[python()]}
        onChange={onChange}
        readOnly={readOnly}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: !readOnly,
          bracketMatching: true,
          autocompletion: !readOnly,
          indentOnInput: !readOnly,
        }}
        style={{ fontSize: 13 }}
      />
    </div>
  )
}
