module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      // expo-router required plugin
      require.resolve('expo-router/babel'),
      // reanimated plugin must be last
      'react-native-reanimated/plugin',
    ],
  };
};
