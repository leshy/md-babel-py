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

        # Python with matplotlib for code blocks
        pythonWithPackages = pkgs.python312.withPackages (ps: [
          ps.matplotlib
          ps.numpy
        ]);

        # Python package - minimal, without propagated deps polluting PATH
        md-babel-py = pkgs.python312Packages.buildPythonApplication {
          pname = "md-babel-py";
          version = "0.1.0";
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
          openscad
          imagemagick
          diagonPkg

          # OpenSCAD needs a virtual framebuffer and GL libs
          xvfb-run
          mesa

          # Asymptote needs LaTeX and dvisvgm
          (texliveSmall.withPackages (ps: [ ps.dvisvgm ]))
        ];

        # Runtime wrapper with controlled PATH - pythonWithPackages first
        md-babel-py-full = pkgs.symlinkJoin {
          name = "md-babel-py-full";
          paths = [ md-babel-py ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            wrapProgram $out/bin/md-babel-py \
              --set PATH ${pkgs.lib.makeBinPath ([ pythonWithPackages ] ++ evaluatorDeps)} \
              --set PYTHONPATH ${md-babel-py}/${pkgs.python312.sitePackages} \
              --set LIBGL_ALWAYS_SOFTWARE 1 \
              --set GALLIUM_DRIVER llvmpipe \
              --set __GLX_VENDOR_LIBRARY_NAME mesa \
              --set LD_LIBRARY_PATH ${pkgs.mesa}/lib:${pkgs.libglvnd}/lib \
              --set LIBGL_DRIVERS_PATH ${pkgs.mesa}/lib/dri
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
