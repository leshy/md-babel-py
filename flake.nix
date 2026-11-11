{
  description = "md-babel-py - Execute code blocks in markdown files";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    diagon.url = "github:petertrotman/nixpkgs/Diagon";
  };

  outputs = { self, nixpkgs, flake-utils, diagon }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        diagonPkg = diagon.legacyPackages.${system}.diagon;
        isLinux = pkgs.stdenv.isLinux;

        # asciichartpy isn't in nixpkgs
        asciichartpy = pkgs.python312Packages.buildPythonPackage rec {
          pname = "asciichartpy";
          version = "1.5.25";
          format = "wheel";  # sdist's setup.py reads a README.md it doesn't ship
          src = pkgs.fetchPypi {
            inherit pname version format;
            dist = "py2.py3";
            python = "py2.py3";
            hash = "sha256-M8QXo8jvfQoRuY656m3ZssGxdVnlObIHoX0m1DAtAlg=";
          };
        };

        # Python with plotting libs for code blocks
        pythonWithPackages = pkgs.python312.withPackages (ps: [
          ps.matplotlib
          ps.numpy
          asciichartpy
        ]);

        # Python package - minimal, without propagated deps polluting PATH
        md-babel-py = pkgs.python312Packages.buildPythonApplication {
          pname = "md-babel-py";
          version = "1.0.6";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = [ pkgs.python312Packages.setuptools ];

          # Don't wrap - we'll do our own wrapping
          dontWrapPythonPrograms = true;

          meta = {
            description = "Execute code blocks in markdown files with session support";
            license = pkgs.lib.licenses.mit;
          };
        };

        # On macOS, xvfb-run is not available. Provide a passthrough stub so the
        # default openscad config (which calls "xvfb-run -a openscad ...") works.
        # macOS OpenSCAD can render headlessly without a virtual framebuffer.
        xvfbRunStub = pkgs.writeShellScriptBin "xvfb-run" ''
          # Strip all leading flags then exec the remaining command directly.
          # This allows "xvfb-run -a openscad ..." to work on macOS.
          while [ "$#" -gt 0 ]; do
            case "$1" in
              --) shift; break ;;
              -*) shift ;;
              *) break ;;
            esac
          done
          exec "$@"
        '';

        xvfbDep = if isLinux then pkgs.xvfb-run else xvfbRunStub;

        # On macOS, openscad is an .app bundle with no bin/ entry.
        # Wrap the actual binary so it's accessible as "openscad" on PATH.
        openscadDep = if isLinux
          then pkgs.openscad
          else pkgs.writeShellScriptBin "openscad" ''
            exec "${pkgs.openscad}/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD" "$@"
          '';

        # All evaluator dependencies
        evaluatorDeps = with pkgs; [
          # Core
          bash
          coreutils

          # Languages
          pythonWithPackages
          nodejs

          # Graphics tools
          graphviz
          asymptote
          pikchr
          openscadDep
          imagemagick
          diagonPkg

          # Virtual framebuffer (Linux native) or passthrough stub (macOS)
          xvfbDep

          # Asymptote needs LaTeX and dvisvgm
          (texliveSmall.withPackages (ps: [ ps.dvisvgm ]))
        ] ++ pkgs.lib.optionals isLinux [
          # Linux-only: Mesa software GL rendering for headless OpenSCAD
          mesa
        ];

        # Runtime wrapper with controlled PATH - pythonWithPackages first
        md-babel-py-full = pkgs.symlinkJoin {
          name = "md-babel-py-full";
          paths = [ md-babel-py ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            # Run md-babel itself on pythonWithPackages: the executor runs python
            # blocks with sys.executable, so blocks see matplotlib/asciichartpy.
            rm $out/bin/md-babel-py
            makeWrapper ${pythonWithPackages}/bin/python3 $out/bin/md-babel-py \
              --add-flags "-m md_babel_py.cli" \
              --set PATH ${pkgs.lib.makeBinPath ([ pythonWithPackages ] ++ evaluatorDeps)} \
              --set PYTHONPATH ${md-babel-py}/${pkgs.python312.sitePackages} \
              ${pkgs.lib.optionalString isLinux ''
              --set LIBGL_ALWAYS_SOFTWARE 1 \
              --set GALLIUM_DRIVER llvmpipe \
              --set __GLX_VENDOR_LIBRARY_NAME mesa \
              --set LD_LIBRARY_PATH ${pkgs.mesa}/lib:${pkgs.libglvnd}/lib \
              --set LIBGL_DRIVERS_PATH ${pkgs.mesa}/lib/dri \
              ''}
          '';
        };

      in {
        packages = {
          default = md-babel-py-full;
          minimal = md-babel-py;
        };

        apps.default = {
          type = "app";
          program = "${md-babel-py-full}/bin/md-babel-py";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            # Don't include md-babel-py here - use local editable install instead
            pkgs.python312Packages.pytest
            pkgs.python312Packages.mypy
            pkgs.python312Packages.ruff
          ] ++ evaluatorDeps;
        };

        # Docker image
        packages.docker = pkgs.dockerTools.buildLayeredImage {
          name = "md-babel-py";
          tag = "latest";

          contents = [
            md-babel-py-full
            pkgs.bashInteractive
            pkgs.coreutils
          ] ++ evaluatorDeps;

          # Create /usr/bin/env symlink and /tmp
          extraCommands = ''
            mkdir -p usr/bin
            ln -s ${pkgs.coreutils}/bin/env usr/bin/env
            mkdir -p tmp
            chmod 1777 tmp
          '';

          config = {
            Entrypoint = [ "${md-babel-py-full}/bin/md-babel-py" ];
            WorkingDir = "/work";
            Env = [
              "HOME=/root"
              "FONTCONFIG_FILE=${pkgs.fontconfig.out}/etc/fonts/fonts.conf"
            ];
          };
        };
      }
    );
}
