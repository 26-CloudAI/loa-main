import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'

interface PythonEditorProps {
  value: string
  onChange: (value: string) => void
  hasError?: boolean
}

export default function PythonEditor({ value, onChange, hasError }: PythonEditorProps) {
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
        height="480px"
        theme={vscodeDark}
        extensions={[python()]}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          bracketMatching: true,
          autocompletion: true,
          indentOnInput: true,
        }}
        style={{ fontSize: 13 }}
      />
    </div>
  )
}
