package vn.logisimmcp.live;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Minimal dependency-free JSON reader/writer for the loopback protocol. */
final class Json {
  private final String text;
  private int pos;

  private Json(String text) {
    this.text = text;
  }

  static Object parse(String text) {
    final Json p = new Json(text);
    p.skipWs();
    final Object value = p.value();
    p.skipWs();
    if (p.pos != text.length()) throw p.error("trailing characters");
    return value;
  }

  @SuppressWarnings("unchecked")
  static Map<String, Object> obj(Object o) {
    if (o instanceof Map) return (Map<String, Object>) o;
    throw new IllegalArgumentException("expected a JSON object");
  }

  @SuppressWarnings("unchecked")
  static List<Object> arr(Object o) {
    if (o == null) return List.of();
    if (o instanceof List) return (List<Object>) o;
    throw new IllegalArgumentException("expected a JSON array");
  }

  static String str(Object o) {
    return o == null ? null : o.toString();
  }

  static int integer(Object o) {
    if (o instanceof Number n) return n.intValue();
    throw new IllegalArgumentException("expected a number, got " + o);
  }

  private IllegalArgumentException error(String msg) {
    return new IllegalArgumentException("JSON " + msg + " at offset " + pos);
  }

  private void skipWs() {
    while (pos < text.length() && Character.isWhitespace(text.charAt(pos))) pos++;
  }

  private Object value() {
    if (pos >= text.length()) throw error("unexpected end");
    final char c = text.charAt(pos);
    switch (c) {
      case '{':
        return object();
      case '[':
        return array();
      case '"':
        return string();
      case 't':
        expect("true");
        return Boolean.TRUE;
      case 'f':
        expect("false");
        return Boolean.FALSE;
      case 'n':
        expect("null");
        return null;
      default:
        return number();
    }
  }

  private void expect(String word) {
    if (!text.startsWith(word, pos)) throw error("expected " + word);
    pos += word.length();
  }

  private Map<String, Object> object() {
    final Map<String, Object> map = new LinkedHashMap<>();
    pos++;
    skipWs();
    if (peek() == '}') {
      pos++;
      return map;
    }
    while (true) {
      skipWs();
      if (peek() != '"') throw error("expected key");
      final String key = string();
      skipWs();
      if (peek() != ':') throw error("expected ':'");
      pos++;
      skipWs();
      map.put(key, value());
      skipWs();
      final char c = peek();
      pos++;
      if (c == '}') return map;
      if (c != ',') throw error("expected ',' or '}'");
    }
  }

  private List<Object> array() {
    final List<Object> list = new ArrayList<>();
    pos++;
    skipWs();
    if (peek() == ']') {
      pos++;
      return list;
    }
    while (true) {
      skipWs();
      list.add(value());
      skipWs();
      final char c = peek();
      pos++;
      if (c == ']') return list;
      if (c != ',') throw error("expected ',' or ']'");
    }
  }

  private char peek() {
    if (pos >= text.length()) throw error("unexpected end");
    return text.charAt(pos);
  }

  private String string() {
    pos++; // opening quote
    final StringBuilder b = new StringBuilder();
    while (true) {
      final char c = peek();
      pos++;
      if (c == '"') return b.toString();
      if (c != '\\') {
        b.append(c);
        continue;
      }
      final char e = peek();
      pos++;
      switch (e) {
        case '"', '\\', '/' -> b.append(e);
        case 'b' -> b.append('\b');
        case 'f' -> b.append('\f');
        case 'n' -> b.append('\n');
        case 'r' -> b.append('\r');
        case 't' -> b.append('\t');
        case 'u' -> {
          if (pos + 4 > text.length()) throw error("bad unicode escape");
          b.append((char) Integer.parseInt(text.substring(pos, pos + 4), 16));
          pos += 4;
        }
        default -> throw error("bad escape");
      }
    }
  }

  private Number number() {
    final int start = pos;
    while (pos < text.length() && "+-0123456789.eE".indexOf(text.charAt(pos)) >= 0) pos++;
    final String s = text.substring(start, pos);
    if (s.isEmpty()) throw error("unexpected character");
    if (s.contains(".") || s.contains("e") || s.contains("E")) return Double.parseDouble(s);
    return Long.parseLong(s);
  }

  // ------------------------------------------------------------------ writer

  static String write(Object o) {
    final StringBuilder b = new StringBuilder();
    write(b, o);
    return b.toString();
  }

  private static void write(StringBuilder b, Object o) {
    if (o == null) {
      b.append("null");
    } else if (o instanceof String s) {
      quote(b, s);
    } else if (o instanceof Number || o instanceof Boolean) {
      b.append(o);
    } else if (o instanceof Map<?, ?> m) {
      b.append('{');
      boolean first = true;
      for (final Map.Entry<?, ?> e : m.entrySet()) {
        if (!first) b.append(',');
        first = false;
        quote(b, String.valueOf(e.getKey()));
        b.append(':');
        write(b, e.getValue());
      }
      b.append('}');
    } else if (o instanceof Iterable<?> it) {
      b.append('[');
      boolean first = true;
      for (final Object item : it) {
        if (!first) b.append(',');
        first = false;
        write(b, item);
      }
      b.append(']');
    } else if (o instanceof int[] ints) {
      b.append('[');
      for (int i = 0; i < ints.length; i++) {
        if (i > 0) b.append(',');
        b.append(ints[i]);
      }
      b.append(']');
    } else {
      quote(b, o.toString());
    }
  }

  private static void quote(StringBuilder b, String s) {
    b.append('"');
    for (int i = 0; i < s.length(); i++) {
      final char c = s.charAt(i);
      switch (c) {
        case '"' -> b.append("\\\"");
        case '\\' -> b.append("\\\\");
        case '\n' -> b.append("\\n");
        case '\r' -> b.append("\\r");
        case '\t' -> b.append("\\t");
        default -> {
          if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
          else b.append(c);
        }
      }
    }
    b.append('"');
  }
}
