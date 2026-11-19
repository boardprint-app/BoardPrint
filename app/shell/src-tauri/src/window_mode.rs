// Modo de ventana y escala de la interfaz (docs/PLAN_PIZARRA.md D50, D60, D183).
//
// Los guarda el backend en `settings.toml` (`[ventana] modo` y `escala`) y los aplica el shell:
// al abrir y cada vez que el fichero cambia, sin IPC con la interfaz (R3). Un valor ilegible
// vale el de por defecto (maximizada y 100 %) y una escala fuera de 80-150 se lleva al borde,
// igual que `Settings.scale` del backend.

use std::path::Path;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Mode {
    Maximized,
    Fullscreen,
    Borderless,
    Windowed,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WindowSettings {
    pub mode: Mode,
    pub scale: u32, // %
}

pub const DEFAULT: WindowSettings = WindowSettings { mode: Mode::Maximized, scale: 100 };
const SCALE_MIN: i64 = 80;
const SCALE_MAX: i64 = 150;
const SCALE_STEP: i64 = 10;

pub fn parse(text: &str) -> WindowSettings {
    let table = match text.parse::<toml::Table>() {
        Ok(t) => t,
        Err(_) => return DEFAULT,
    };
    let window = match table.get("ventana").and_then(|v| v.as_table()) {
        Some(w) => w,
        None => return DEFAULT,
    };
    let mode = match window.get("modo").and_then(|v| v.as_str()) {
        Some("pantalla_completa") => Mode::Fullscreen,
        Some("sin_bordes") => Mode::Borderless,
        Some("ventana") => Mode::Windowed,
        _ => Mode::Maximized,
    };
    let raw = match window.get("escala") {
        Some(toml::Value::Integer(i)) => Some(*i as f64),
        Some(toml::Value::Float(f)) if f.is_finite() => Some(*f),
        _ => None,
    };
    let scale = match raw {
        Some(v) => {
            let rounded = ((v / SCALE_STEP as f64).round() as i64) * SCALE_STEP;
            rounded.clamp(SCALE_MIN, SCALE_MAX) as u32
        }
        None => DEFAULT.scale,
    };
    WindowSettings { mode, scale }
}

pub fn read(path: &Path) -> WindowSettings {
    std::fs::read_to_string(path).map(|t| parse(&t)).unwrap_or(DEFAULT)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sin_fichero_o_ilegible_es_maximizada_y_100() {
        assert_eq!(parse(""), DEFAULT);
        assert_eq!(parse("esto no es [ toml"), DEFAULT);
        assert_eq!(read(Path::new("no-existe/settings.toml")), DEFAULT);
    }

    #[test]
    fn un_modo_o_una_escala_ilegibles_dan_los_de_por_defecto() {
        let s = parse("[ventana]\nmodo = \"flotante\"\nescala = \"grande\"\n");
        assert_eq!(s, DEFAULT);
        assert_eq!(parse("ventana = 3\n"), DEFAULT);
    }

    #[test]
    fn lee_los_cuatro_modos() {
        assert_eq!(parse("[ventana]\nmodo = \"pantalla_completa\"").mode, Mode::Fullscreen);
        assert_eq!(parse("[ventana]\nmodo = \"sin_bordes\"").mode, Mode::Borderless);
        assert_eq!(parse("[ventana]\nmodo = \"ventana\"").mode, Mode::Windowed);
        assert_eq!(parse("[ventana]\nmodo = \"maximizada\"").mode, Mode::Maximized);
    }

    #[test]
    fn una_escala_fuera_de_rango_se_lleva_al_borde() {
        assert_eq!(parse("[ventana]\nescala = 400").scale, 150);
        assert_eq!(parse("[ventana]\nescala = 10").scale, 80);
        assert_eq!(parse("[ventana]\nescala = 114").scale, 110);
        assert_eq!(parse("[ventana]\nescala = 125.0").scale, 130);
        assert_eq!(parse("[ventana]\nescala = 120").scale, 120);
    }

    #[test]
    fn el_resto_del_fichero_no_molesta() {
        let s = parse("skin = \"cad\"\n[[workspaces]]\nid = \"a\"\n[ventana]\nmodo = \"ventana\"\nescala = 90\n");
        assert_eq!(s, WindowSettings { mode: Mode::Windowed, scale: 90 });
    }
}
