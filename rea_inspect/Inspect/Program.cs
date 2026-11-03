using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.MetadataLoadContext;
using System.Reflection.PortableExecutable;

var baseDir = @"C:\Program Files (x86)\Steam\steamapps\common\Shape of Dreams\Shape of Dreams_Data\Managed";

var mlc = new MetadataLoadContext(
    new ReflectionMetadataResolver(),
    (name) => null  // don't try to load dependencies
);

var targetDlls = new[]
{
    "Assembly-CSharp.dll",
    "Dew.Core.dll",
    "Dew.Contents.dll",
    "ClassLibrary1.dll",
    "DemiLib.dll",
};

var keywords = new[] { "camera", "player", "move", "dash", "follow", "shake", "cinemachine", "dew", "controller", "character", "input", "pitch", "yaw", "rig", "motor" };

foreach (var dll in targetDlls)
{
    var path = Path.Combine(baseDir, dll);
    if (!File.Exists(path))
    {
        Console.WriteLine($"=== {dll}: NOT FOUND ===");
        continue;
    }

    Console.WriteLine($"\n{'='.PadRight(80)}");
    Console.WriteLine($"=== {dll} ===");
    Console.WriteLine($"{'='.PadRight(80)}");

    try
    {
        using var peStream = File.OpenRead(path);
        using var peReader = new PEReader(peStream);
        var assembly = mlc.LoadFromStream(peStream);

        var types = assembly.GetTypes()
            .Where(t => keywords.Any(k => t.Name.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0 ||
                        t.Namespace?.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0))
            .OrderBy(t => t.Namespace)
            .ThenBy(t => t.Name)
            .ToList();

        Console.WriteLine($"Relevant types: {types.Count}");

        foreach (var type in types)
        {
            Console.WriteLine($"\n  [{type.Namespace}] {type.Name}");
            Console.WriteLine($"    Base: {type.BaseType?.Name ?? "none"}, Interfaces: {string.Join(", ", type.GetInterfaces().Select(i => i.Name))}");

            // Methods
            var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                .Where(m => keywords.Any(k => m.Name.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(m => m.Name)
                .Take(20)
                .ToList();
            if (methods.Count > 0)
            {
                Console.WriteLine($"    Methods ({methods.Count} shown):");
                foreach (var m in methods)
                {
                    var attrs = "";
                    if (m.IsPrivate) attrs += "private ";
                    else if (m.IsPublic) attrs += "public ";
                    else if (m.IsFamily) attrs += "protected ";
                    if (m.IsStatic) attrs += "static ";
                    Console.WriteLine($"      {attrs}{m.ReturnType.Name} {m.Name}({string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name))})");
                }
            }

            // Fields
            var fields = type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                .Where(f => keywords.Any(k => f.Name.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(f => f.Name)
                .Take(15)
                .ToList();
            if (fields.Count > 0)
            {
                Console.WriteLine($"    Fields ({fields.Count} shown):");
                foreach (var f in fields)
                {
                    var attrs = "";
                    if (f.IsPrivate) attrs += "private ";
                    else if (f.IsPublic) attrs += "public ";
                    else if (f.IsFamily) attrs += "protected ";
                    if (f.IsStatic) attrs += "static ";
                    Console.WriteLine($"      {attrs}{f.FieldType.Name} {f.Name}");
                }
            }

            // Properties
            var props = type.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                .Where(p => keywords.Any(k => p.Name.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(p => p.Name)
                .Take(10)
                .ToList();
            if (props.Count > 0)
            {
                Console.WriteLine($"    Properties ({props.Count} shown):");
                foreach (var p in props)
                {
                    Console.WriteLine($"      {p.PropertyType.Name} {p.Name}");
                }
            }
        }
    }
    catch (Exception ex)
    {
        Console.WriteLine($"ERROR: {ex.Message}");
    }
}

Console.WriteLine("\nDone.");
