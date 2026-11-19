"""Punto de entrada del ejecutable empaquetado (PyInstaller, ver app/shell/README.md)."""
import multiprocessing

if __name__ == "__main__":
    # El proceso de cálculo de los bloques (D92) es este mismo ejecutable arrancado por
    # multiprocessing: freeze_support lo desvía a su función antes de importar el servidor.
    multiprocessing.freeze_support()
    import sys
    if "--probe-pack-env" in sys.argv:
        # Prueba del entorno de paquetes en la app instalada (PLAN_PAQUETES FF 10.1 paso 1).
        from pizarra import pack_env
        sys.exit(pack_env.main(sys.argv[1:]))
    from pizarra.server import main
    main()
