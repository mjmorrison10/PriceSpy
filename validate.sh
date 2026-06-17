#!/bin/bash
# Pre-deploy validation — catches JS syntax errors before they reach Render
FILE="$1"
echo "=== Validating $FILE ==="

# 1. Extract JS section
JS_START=$(grep -n '<script>' "$FILE" | head -1 | cut -d: -f1)
JS_END=$(grep -n '</script>' "$FILE" | tail -1 | cut -d: -f1)
sed -n "${JS_START},${JS_END}p" "$FILE" > /tmp/js_check.txt

# 2. Check parentheses balance
OPEN=$(grep -o '(' /tmp/js_check.txt | wc -l)
CLOSE=$(grep -o ')' /tmp/js_check.txt | wc -l)
if [ "$OPEN" -ne "$CLOSE" ]; then
    echo "❌ PARENS UNBALANCED: $OPEN open, $CLOSE close (diff: $((OPEN - CLOSE)))"
    exit 1
fi
echo "✅ Parens balanced ($OPEN)"

# 3. Check curly braces balance
OBRACE=$(grep -o '{' /tmp/js_check.txt | wc -l)
CBRACE=$(grep -o '}' /tmp/js_check.txt | wc -l)
if [ "$OBRACE" -ne "$CBRACE" ]; then
    echo "❌ BRACES UNBALANCED: $OBRACE open, $CBRACE close (diff: $((OBRACE - CBRACE)))"
    exit 1
fi
echo "✅ Braces balanced ($OBRACE)"

# 4. Check for console.log lines that may be unterminated (actual unterminated string, not false positive)
if grep -E "console\.log\(['\"].*)" /tmp/js_check.txt | grep -vE "console\.log\(['\"][^'\"]*['\"].*\);" | grep -vE "console\.log\(['\"][^'\"]*['\"],.*\);" >/dev/null; then
    # This is a heuristic; don't fail automatically because template literals and multiline strings exist.
    echo "⚠️ Some console.log lines look suspicious — review manually"
fi

echo "✅ Validation passed"
