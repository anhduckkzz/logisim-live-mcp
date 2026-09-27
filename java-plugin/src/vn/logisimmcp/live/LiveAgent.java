package vn.logisimmcp.live;

import com.cburch.logisim.Main;
import com.cburch.logisim.proj.Project;
import com.cburch.logisim.proj.ProjectActions;
import com.cburch.logisim.proj.Projects;
import java.awt.Component;
import java.awt.Frame;
import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.lang.instrument.Instrumentation;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.SwingUtilities;

/**
 * Live-control companion for Logisim Evolution, loaded with {@code -javaagent}.
 *
 * <p>It runs inside the Logisim JVM (like the Blender MCP add-on runs inside Blender) and
 * listens on a loopback-only TCP port. The MCP bridge uses it to open or reload a saved
 * project in the already running application instead of starting a new process.
 *
 * <p>Protocol: one request line per connection, tab separated, UTF-8:
 * {@code <token> TAB <command> [TAB <arg>...]}. The response is one line:
 * {@code OK TAB <json>} or {@code ERR TAB <code> TAB <message>}.
 */
public final class LiveAgent {
  public static final String PROTOCOL_VERSION = "2";
  private static final String UNNAMED_PREFIX = ".logisim-unnamed-autosave_";
  private static final String UNNAMED_SUFFIX = ".circ.autosave";

  private static volatile String token = "";
  private static final List<String> archivedAtStartup =
      Collections.synchronizedList(new ArrayList<>());

  private LiveAgent() {}

  public static void premain(String agentArgs, Instrumentation inst) {
    start(agentArgs);
  }

  public static void agentmain(String agentArgs, Instrumentation inst) {
    start(agentArgs);
  }

  private static void start(String agentArgs) {
    final Map<String, String> opts = parseArgs(agentArgs);
    final String envToken = System.getenv("LOGISIM_MCP_LIVE_TOKEN");
    token = envToken != null ? envToken : opts.getOrDefault("token", "");
    int port = 51235;
    try {
      port = Integer.parseInt(opts.getOrDefault("port", "51235"));
    } catch (NumberFormatException ignored) {
      // keep default
    }
    final boolean archive =
        !"0".equals(opts.get("archiveAutosaves"))
            && !"0".equals(System.getenv("LOGISIM_MCP_ARCHIVE_AUTOSAVES"));
    if (archive) {
      archiveUnnamedAutosaves();
      // The bridge passes the project it launches with, so its stale autosave cannot
      // trigger Logisim's "load autosave / discard" prompt either.
      final String launchFile = System.getenv("LOGISIM_MCP_LAUNCH_FILE");
      if (launchFile != null && !launchFile.isBlank()) {
        final String archived = archiveNamedAutosave(new File(launchFile));
        if (archived != null) archivedAtStartup.add(archived);
      }
    }
    final int boundPort = port;
    final Thread server = new Thread(() -> serve(boundPort), "logisim-mcp-live");
    server.setDaemon(true);
    server.start();
  }

  static Map<String, String> parseArgs(String args) {
    final Map<String, String> result = new HashMap<>();
    if (args == null || args.isBlank()) return result;
    for (final String part : args.split(",")) {
      final int eq = part.indexOf('=');
      if (eq > 0) result.put(part.substring(0, eq).trim(), part.substring(eq + 1).trim());
    }
    return result;
  }

  // ---------------------------------------------------------------- autosave handling

  private static Path archiveDir() throws IOException {
    final String stamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").format(LocalDateTime.now());
    final Path dir =
        Path.of(System.getProperty("user.home"), ".logisim-mcp", "autosave-archive", stamp);
    Files.createDirectories(dir);
    return dir;
  }

  /**
   * Logisim's Startup shows a "save / save and load / discard" dialog followed by a file
   * chooser for every leftover unnamed autosave in the home folder. Move them aside (never
   * delete) so the application opens straight to the requested project.
   */
  static void archiveUnnamedAutosaves() {
    final File home = new File(System.getProperty("user.home"));
    final File[] leftovers =
        home.listFiles(
            (dir, name) -> name.startsWith(UNNAMED_PREFIX) && name.endsWith(UNNAMED_SUFFIX));
    if (leftovers == null || leftovers.length == 0) return;
    try {
      final Path dir = archiveDir();
      for (final File f : leftovers) {
        final Path target = dir.resolve(f.getName());
        Files.move(f.toPath(), target, StandardCopyOption.REPLACE_EXISTING);
        archivedAtStartup.add(target.toString());
      }
    } catch (IOException e) {
      System.err.println("[logisim-mcp-live] could not archive autosaves: " + e);
    }
  }

  /** Same naming rule as Logisim's Loader.determineAutosaveName for a named file. */
  static File namedAutosaveFor(File base) {
    final String ext = base.getName().endsWith(".circ") ? ".autosave" : ".circ.autosave";
    return new File(base.getParentFile(), "." + base.getName() + ext);
  }

  /** A stale autosave next to the file makes Logisim ask "load autosave or discard". */
  static String archiveNamedAutosave(File base) {
    final File autosave = namedAutosaveFor(base);
    if (!autosave.isFile()) return null;
    try {
      final Path target = archiveDir().resolve(autosave.getName());
      Files.move(autosave.toPath(), target, StandardCopyOption.REPLACE_EXISTING);
      return target.toString();
    } catch (IOException e) {
      System.err.println("[logisim-mcp-live] could not archive " + autosave + ": " + e);
      return null;
    }
  }

  // ---------------------------------------------------------------- server

  private static void serve(int port) {
    try (ServerSocket server = new ServerSocket(port, 8, InetAddress.getLoopbackAddress())) {
      while (true) {
        try (Socket socket = server.accept()) {
          socket.setSoTimeout(60_000);
          handle(socket);
        } catch (IOException e) {
          System.err.println("[logisim-mcp-live] connection error: " + e);
        }
      }
    } catch (IOException e) {
      System.err.println(
          "[logisim-mcp-live] control port " + port + " unavailable, live control disabled: " + e);
    }
  }

  private static void handle(Socket socket) throws IOException {
    final BufferedReader in =
        new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
    final Writer out = new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8);
    final String line = in.readLine();
    String response;
    try {
      response = dispatch(line);
    } catch (Throwable t) {
      response = err("INTERNAL", t.toString());
    }
    out.write(response);
    out.write("\n");
    out.flush();
  }

  static String dispatch(String line) throws Exception {
    if (line == null) return err("BAD_REQUEST", "empty request");
    final String[] parts = line.split("\t", -1);
    if (parts.length < 2) return err("BAD_REQUEST", "expected <token> TAB <command>");
    if (!constantTimeEquals(parts[0], token)) return err("AUTH", "invalid token");
    final String command = parts[1];
    switch (command) {
      case "PING":
        return onEdt(LiveAgent::ping);
      case "FOCUS":
        return onEdt(
            () -> {
              final List<Project> projects = Projects.getOpenProjects();
              if (projects.isEmpty()) return err("NOT_READY", "no Logisim window yet");
              bringToFront(projects.get(projects.size() - 1).getFrame());
              return ok("{\"focused\":true}");
            });
      default:
        break;
    }
    if (parts.length < 3) return err("BAD_REQUEST", command + " needs a project path");
    final File file = new File(parts[2]).getCanonicalFile();
    switch (command) {
      case "OPEN":
      case "RELOAD": {
        final boolean force = parts.length > 3 && "1".equals(parts[3]);
        final boolean reload = parts.length <= 4 || !"0".equals(parts[4]);
        final boolean openIfClosed = command.equals("OPEN");
        return onEdt(() -> open(file, force, openIfClosed, reload));
      }
      case "STATUS":
        return onEdt(
            () -> {
              final Project p = findOpen(file);
              if (p == null) return ok("{\"open_in_app\":false}");
              return ok(Json.write(LiveEditor.status(p)));
            });
      case "APPLY": {
        if (parts.length < 6) return err("BAD_REQUEST", "APPLY needs revision, label and ops");
        final long expected = Long.parseLong(parts[3]);
        final String label = parts[4];
        final List<Object> ops = Json.arr(Json.parse(parts[5]));
        return onEdt(
            () -> {
              final Project p = findOpen(file);
              if (p == null) return err("NOT_OPEN", file.getName() + " is not open in Logisim");
              try {
                return ok(Json.write(LiveEditor.apply(p, ops, label, expected)));
              } catch (LiveEditor.Stale stale) {
                return err("STALE", Long.toString(stale.external));
              } catch (LiveEditor.InvalidOp invalid) {
                return err("INVALID", invalid.getMessage());
              }
            });
      }
      case "EXPORT": {
        if (parts.length < 4) return err("BAD_REQUEST", "EXPORT needs a destination");
        final File dest = new File(parts[3]);
        return onEdt(
            () -> {
              final Project p = findOpen(file);
              if (p == null) return err("NOT_OPEN", file.getName() + " is not open in Logisim");
              LiveEditor.export(p, dest, mainFileOf(p));
              return ok(Json.write(LiveEditor.status(p)));
            });
      }
      case "SAVED": {
        if (parts.length < 4) return err("BAD_REQUEST", "SAVED needs the expected state");
        final Map<String, Object> expected = Json.obj(Json.parse(parts[3]));
        return onEdt(
            () -> {
              final Project p = findOpen(file);
              if (p == null) return ok("{\"open_in_app\":false}");
              return ok(Json.write(LiveEditor.verifyAndMarkClean(p, expected, file)));
            });
      }
      case "CATALOG":
      case "DESCRIBE":
      case "DESCRIBE_MANY":
      case "INSPECT":
      case "DRIVE":
      case "SIMULATE": {
        final Map<String, Object> args = parts.length > 3 && !parts[3].isEmpty()
            ? Json.obj(Json.parse(parts[3])) : new LinkedHashMap<>();
        final Callable<String> body = () -> {
          final Project p = findOpen(file);
          if (p == null) return err("NOT_OPEN", file.getName() + " is not open in Logisim");
          try {
            final Map<String, Object> out = switch (command) {
              case "CATALOG" -> LiveInspector.catalog(p, Json.str(args.get("library")), Json.str(args.get("query")));
              case "DESCRIBE" -> LiveInspector.describe(p, Json.str(args.get("lib")), Json.str(args.get("name")),
                  LiveEditor.props(args.get("props")));
              case "DESCRIBE_MANY" -> LiveInspector.describeMany(p, Json.arr(args.get("items")));
              case "INSPECT" -> LiveInspector.inspect(p, Json.str(args.get("circuit")),
                  !Boolean.FALSE.equals(args.get("values")), Boolean.TRUE.equals(args.get("attributes")));
              case "DRIVE" -> LiveInspector.drive(p, Json.str(args.get("circuit")), Json.obj(args.get("values")));
              default -> LiveInspector.simulate(p, Json.str(args.get("circuit")), args);
            };
            return ok(Json.write(out));
          } catch (LiveEditor.InvalidOp invalid) {
            return err("INVALID", invalid.getMessage());
          }
        };
        // Simulation runs in a private circuit state on this worker thread so the window stays
        // responsive; everything else reads the model on the Swing thread.
        return command.equals("SIMULATE") ? body.call() : onEdt(body);
      }
      case "SHOW": {
        final String circuit = parts.length > 3 ? parts[3] : null;
        return onEdt(
            () -> {
              final Project p = findOpen(file);
              if (p == null) return err("NOT_OPEN", file.getName() + " is not open in Logisim");
              try {
                final Map<String, Object> st = LiveEditor.show(p, circuit);
                bringToFront(p.getFrame());
                return ok(Json.write(st));
              } catch (LiveEditor.InvalidOp invalid) {
                return err("INVALID", invalid.getMessage());
              }
            });
      }
      default:
        return err("BAD_REQUEST", "unknown command " + command);
    }
  }

  private static boolean constantTimeEquals(String a, String b) {
    return MessageDigest.isEqual(
        a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
  }

  private static String onEdt(Callable<String> body) throws Exception {
    if (SwingUtilities.isEventDispatchThread()) return body.call();
    final AtomicReference<String> result = new AtomicReference<>();
    final AtomicReference<Exception> failure = new AtomicReference<>();
    SwingUtilities.invokeAndWait(
        () -> {
          try {
            result.set(body.call());
          } catch (Exception e) {
            failure.set(e);
          }
        });
    if (failure.get() != null) throw failure.get();
    return result.get();
  }

  // ---------------------------------------------------------------- commands

  private static String ping() {
    final Map<String, Object> m = new LinkedHashMap<>();
    final List<Project> projects = Projects.getOpenProjects();
    m.put("ready", !projects.isEmpty());
    m.put("protocol", PROTOCOL_VERSION);
    m.put("pid", ProcessHandle.current().pid());
    final String version = Main.class.getPackage().getImplementationVersion();
    m.put("logisim_version", version == null ? "unknown" : version);
    final List<Object> list = new ArrayList<>();
    for (final Project p : projects) {
      final File f = mainFileOf(p);
      final Map<String, Object> entry = new LinkedHashMap<>();
      entry.put("path", f == null ? null : f.getAbsolutePath());
      entry.putAll(LiveEditor.status(p));
      list.add(entry);
    }
    m.put("projects", list);
    synchronized (archivedAtStartup) {
      m.put("archived_autosaves_at_startup", new ArrayList<>(archivedAtStartup));
    }
    return ok(Json.write(m));
  }

  static File mainFileOf(Project p) {
    if (p.getLogisimFile() == null || p.getLogisimFile().getLoader() == null) return null;
    return p.getLogisimFile().getLoader().getMainFile();
  }

  private static Project findOpen(File canonical) {
    for (final Project p : Projects.getOpenProjects()) {
      final File f = mainFileOf(p);
      if (f == null) continue;
      try {
        if (f.getCanonicalFile().equals(canonical)) return p;
      } catch (IOException ignored) {
        if (f.getAbsoluteFile().equals(canonical)) return p;
      }
    }
    return null;
  }

  private static String open(File file, boolean force, boolean openIfClosed, boolean reload) {
    if (!file.isFile()) return err("NOT_FOUND", "file does not exist: " + file);
    final Project existing = findOpen(file);
    if (existing == null && !openIfClosed) {
      return ok("{\"open_in_app\":false,\"reloaded\":false}");
    }
    if (existing != null && !reload) {
      // Already showing this project: just bring it forward, keep undo history and zoom.
      bringToFront(existing.getFrame());
      final Map<String, Object> st = LiveEditor.status(existing);
      st.put("reloaded", false);
      st.put("action", "shown");
      return ok(Json.write(st));
    }
    boolean discarded = false;
    if (existing != null && existing.isFileDirty()) {
      if (!force) {
        return err(
            "DIRTY",
            "The Logisim window for "
                + file.getName()
                + " has unsaved edits; save or discard them in Logisim, or retry with"
                + " force_reload=true to discard them.");
      }
      discarded = true;
    }
    final String archived = archiveNamedAutosave(file);

    Project result;
    LiveEditor.internal = true;
    try {
      if (existing != null) {
        if (discarded) existing.setFileAsClean();
        // doOpen finds the clean project by its own File object and reloads it in place.
        result = ProjectActions.doOpen((Component) null, (Project) null, mainFileOf(existing));
      } else {
        Project base = null;
        for (final Project p : Projects.getOpenProjects()) {
          if (p.isStartupScreen() && !p.isFileDirty()) {
            base = p; // reuse the empty "Untitled" start window instead of adding another one
            break;
          }
        }
        result = ProjectActions.doOpen((Component) null, base, file);
      }
    } finally {
      LiveEditor.internal = false;
    }
    if (result == null) return err("LOAD_FAILED", "Logisim could not load " + file);
    bringToFront(result.getFrame());
    final Map<String, Object> st = LiveEditor.status(result);
    st.put("reloaded", existing != null);
    st.put("action", existing != null ? "reloaded" : "opened");
    st.put("discarded_gui_edits", discarded);
    st.put("archived_autosave", archived);
    return ok(Json.write(st));
  }

  private static void bringToFront(Frame frame) {
    if (frame == null) return;
    if ((frame.getExtendedState() & Frame.ICONIFIED) != 0) {
      frame.setExtendedState(frame.getExtendedState() & ~Frame.ICONIFIED);
    }
    frame.setVisible(true);
    // Windows refuses plain toFront() for background processes; the always-on-top toggle
    // is the usual Swing workaround and is reverted immediately.
    frame.setAlwaysOnTop(true);
    frame.toFront();
    frame.requestFocus();
    frame.setAlwaysOnTop(false);
  }

  // ---------------------------------------------------------------- tiny JSON helpers

  private static String ok(String json) {
    return "OK\t" + json;
  }

  private static String err(String code, String message) {
    return "ERR\t" + code + "\t" + message.replace('\t', ' ').replace('\n', ' ');
  }
}
